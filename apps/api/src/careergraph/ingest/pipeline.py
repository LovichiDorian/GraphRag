"""End-to-end knowledge-graph construction.

profile.yaml ─┐                       ┌─ schema-guided LLM extraction (cached)
notes/*.md ───┼─► documents ─► chunks ─┤
GitHub repos ─┘   + manifests          └─ mention linking
                     │
                     ▼
canonical skills ─► entity resolution ─► skill evidence (HAS_SKILL strength)
                     │
                     ▼
Louvain communities ─► LLM community reports ─► PageRank ─► embeddings ─► Neo4j
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from typing import Any

import networkx as nx
import orjson

from careergraph.graph.models import ChunkNode, CommunityNode, DocumentNode, EntityNode, KnowledgeGraph
from careergraph.graph.schema import COMMUNITY_EXCLUDED, PPR_EDGE_WEIGHTS, NodeType, RelType
from careergraph.graph.snapshot import EdgeView, EntityView, GraphSnapshot, normalize_name
from careergraph.ingest.cache import KVCache, content_key
from careergraph.ingest.chunking import chunk_markdown
from careergraph.ingest.extract import Extraction, extract, summarize_community
from careergraph.ingest.resolve import add_skill, link_domains, merge_similar_skills
from careergraph.ingest.sources.github import GitHubSource, Repo
from careergraph.ingest.sources.profile import SourceDoc, build_profile_graph, load_notes, load_profile
from careergraph.ingest.techmap import IMPLIES, all_aliases, canonical
from careergraph.llm.gemini import EmbedTask, Gemini, LLMUnavailableError
from careergraph.logs import get_logger
from careergraph.settings import Settings
from careergraph.text import slugify, truncate

log = get_logger(__name__)

_SKIP_DOCS = re.compile(r"(LICEN[CS]E|CHANGELOG|CODE_OF_CONDUCT|CONTRIBUTING|SECURITY|SUPPORT|AUTHORS)", re.I)


async def build_knowledge_graph(settings: Settings, llm: Gemini, cache: KVCache) -> KnowledgeGraph:
    started = time.perf_counter()
    profile = load_profile(settings.profile_path)
    kg = KnowledgeGraph()
    docs = build_profile_graph(profile, kg)
    docs += load_notes(settings.notes_dir)
    person_id = f"person:{profile['person']['id']}"
    for entity in kg.entities.values():
        if entity.type == NodeType.PROJECT and " — " in entity.name:
            entity.aliases = sorted({*entity.aliases, entity.name.split(" — ")[0].strip()})

    # ── GitHub
    github_cfg: dict[str, Any] = profile.get("github") or {}
    user = settings.github_user or github_cfg.get("user")
    overrides: dict[str, dict[str, Any]] = github_cfg.get("overrides") or {}
    repos: list[Repo] = []
    if user:
        source = GitHubSource(settings, user)
        try:
            repos = await source.fetch(
                list(settings.github_repos_include),
                [*github_cfg.get("exclude", []), *settings.github_repos_exclude],
            )
        except Exception as exc:  # noqa: BLE001 - the CV alone still makes a useful graph
            log.warning("github.unavailable", error=str(exc)[:300])
        finally:
            await source.close()
    for repo in repos:
        docs += add_repository(kg, repo, person_id, overrides.get(repo.name, {}))

    # ── schema-guided LLM extraction (bounded concurrency, cached)
    targets = [d for d in docs if d.extract and d.subject in kg.entities]
    semaphore = asyncio.Semaphore(2)

    async def run(doc: SourceDoc) -> tuple[SourceDoc, Extraction | None]:
        subject = kg.entities[doc.subject or ""]
        async with semaphore:
            result = await extract(
                llm,
                cache,
                models=list(settings.extraction_models),
                subject=f"{subject.type.value}: {subject.name}",
                text=doc.text,
            )
        return doc, result

    for doc, extraction in await asyncio.gather(*(run(d) for d in targets)):
        if extraction is not None:
            apply_extraction(kg, doc, extraction)

    # ── entity resolution for skills the ontology does not know
    unknown = [e for e in kg.entities.values() if e.type == NodeType.SKILL and not e.props.get("known")]
    if len(unknown) > 1 and llm.enabled:
        try:
            vectors = await embed_texts(
                llm, cache, settings, [e.name for e in unknown], "SEMANTIC_SIMILARITY"
            )
            merged = merge_similar_skills(kg, [e.id for e in unknown], vectors)
            log.info("resolve.done", unknown_skills=len(unknown), merged=merged)
        except LLMUnavailableError as exc:
            log.warning("resolve.skipped", error=str(exc)[:200])

    apply_implications(kg)
    link_domains(kg)
    compute_skill_evidence(kg, person_id)
    build_chunks(kg, docs)
    await build_communities(kg, llm, cache, settings)
    compute_pagerank(kg)
    try:
        await embed_graph(kg, llm, cache, settings)
    except LLMUnavailableError as exc:
        log.warning("embeddings.skipped", error=str(exc)[:200])

    kg.meta = {
        "profile_revision": profile_revision(settings),
        "entities": len(kg.entities),
        "relations": len(kg.relations),
        "documents": len(kg.documents),
        "chunks": len(kg.chunks),
        "communities": len(kg.communities),
        "repositories": len(repos),
        "repository_names": sorted(r.name for r in repos),
        "seconds": round(time.perf_counter() - started, 1),
        "extraction_models": list(settings.extraction_models),
        "embedding_model": settings.embedding_model,
        "llm_tokens": {"input": llm.stats.input_tokens, "output": llm.stats.output_tokens},
        "cache": {"hits": cache.hits, "misses": cache.misses},
    }
    return kg


# ── GitHub repositories ──────────────────────────────────────────────────────
def add_repository(
    kg: KnowledgeGraph, repo: Repo, person_id: str, override: dict[str, Any]
) -> list[SourceDoc]:
    project_id = (
        f"project:{override['project']}" if override.get("project") else f"project:{slugify(repo.name)}"
    )
    existing = kg.entities.get(project_id)
    languages = repo.top_languages()
    props: dict[str, Any] = {
        "repo_url": repo.url,
        "stars": repo.stars,
        "primary_language": languages[0] if languages else repo.language,
        "languages": languages,
        "topics": repo.topics,
        "pushed_at": repo.pushed_at,
        "created_at": repo.created_at,
        "private": repo.private,
        "renamed": bool(override.get("name")),
    }
    if existing is None:
        kg.add_entity(
            EntityNode(
                id=project_id,
                type=NodeType.PROJECT,
                name=override.get("name") or repo.name,
                description=repo.description,
                aliases=[repo.name] if override.get("name") else [],
                url=repo.homepage or repo.url,
                props={**props, "source": "github"},
                sources=[f"github:{repo.full_name}"],
            )
        )
    else:
        existing.props.update({k: v for k, v in props.items() if v not in (None, [], "")})
        existing.props["source"] = "cv+github"
        existing.aliases = sorted({*existing.aliases, repo.name})
        existing.sources = sorted({*existing.sources, f"github:{repo.full_name}"})
    kg.add_relation(person_id, RelType.BUILT, project_id)

    for tech, evidence in sorted(repo.technologies().items()):
        if sid := add_skill(kg, tech, source=f"github:{repo.full_name}"):
            kg.entities[sid].props["verified_in_code"] = True
            kg.add_relation(project_id, RelType.USES, sid, source="code", evidence=evidence)
    for topic in repo.topics:
        if canonical(topic) and (sid := add_skill(kg, topic, source=f"github:{repo.full_name}")):
            kg.add_relation(project_id, RelType.USES, sid, source="topic", evidence="GitHub topic")

    name = kg.entities[project_id].name
    docs: list[SourceDoc] = []
    blob = f"{repo.url}/blob/{repo.default_branch}"
    if repo.readme is not None:
        docs.append(
            SourceDoc(
                DocumentNode(
                    id=f"github:{repo.full_name}:readme",
                    title=f"GitHub — {name} (README)",
                    kind="readme",
                    source=f"github:{repo.full_name}",
                    url=f"{blob}/{repo.readme.path}",
                    describes=[project_id],
                    updated_at=repo.pushed_at,
                ),
                repo.readme.text,
                subject=project_id,
                extract=True,
            )
        )
    docs.extend(
        SourceDoc(
            DocumentNode(
                id=f"github:{repo.full_name}:{slugify(doc.path)}",
                title=f"GitHub — {name} ({doc.path})",
                kind="doc",
                source=f"github:{repo.full_name}",
                url=f"{blob}/{doc.path}",
                describes=[project_id],
                updated_at=repo.pushed_at,
            ),
            doc.text,
        )
        for doc in [d for d in repo.docs if not _SKIP_DOCS.search(d.path)][:3]
    )
    docs.append(
        SourceDoc(
            DocumentNode(
                id=f"github:{repo.full_name}:analysis",
                title=f"GitHub — {name} (code analysis)",
                kind="repo",
                source=f"github:{repo.full_name}",
                url=repo.url,
                describes=[project_id],
                updated_at=repo.pushed_at,
            ),
            repo.profile_text(),
            subject=project_id,
            extract=repo.readme is None,
        )
    )
    return docs


def apply_extraction(kg: KnowledgeGraph, doc: SourceDoc, extraction: Extraction) -> None:
    subject = kg.entities[doc.subject or ""]
    if subject.type == NodeType.PROJECT:
        from_github_only = subject.props.get("source") == "github"
        if extraction.summary and (from_github_only or not subject.description):
            if subject.description and subject.description not in extraction.summary:
                subject.props["github_description"] = subject.description
            subject.description = extraction.summary
        if not subject.props.get("highlights") and extraction.highlights:
            subject.props["highlights"] = extraction.highlights
        if from_github_only and not subject.props.get("renamed") and extraction.display_name:
            display = extraction.display_name.strip()
            if display and normalize_name(display) != normalize_name(subject.name) and len(display) <= 60:
                subject.aliases = sorted({*subject.aliases, subject.name})
                subject.name = display
        if extraction.application_domains:
            subject.props["application_domains"] = [d.lower() for d in extraction.application_domains[:5]]
        if not extraction.is_substantial:
            subject.props["minor"] = True
    relation = RelType.USES if subject.type == NodeType.PROJECT else RelType.USED
    names: dict[str, str] = {}
    for skill in extraction.skills:
        sid = add_skill(kg, skill.name, source=doc.node.id, category=skill.category)
        if sid is None:
            continue
        names[normalize_name(skill.name)] = sid
        kg.add_relation(subject.id, relation, sid, source="llm", how=truncate(skill.how_used, 140))
    for rel in extraction.relations:
        a, b = names.get(normalize_name(rel.source)), names.get(normalize_name(rel.target))
        if a and b and a != b:
            kg.add_relation(a, RelType.RELATED_TO, b, source="llm")


# ── derived evidence ─────────────────────────────────────────────────────────
def apply_implications(kg: KnowledgeGraph) -> None:
    """Propagate umbrella skills: a project using LangGraph also demonstrates AI agents and LLMs."""
    for rel in list(kg.relations):
        if rel.type not in (RelType.USES, RelType.USED):
            continue
        skill = kg.entities.get(rel.target)
        for implied in IMPLIES.get(skill.name, ()) if skill else ():
            if sid := add_skill(kg, implied, source=f"implied:{skill.name if skill else ''}"):
                kg.add_relation(rel.source, rel.type, sid, source="implied", via=skill.name if skill else "")
            if sid and skill and not kg.has_relation(skill.id, RelType.RELATED_TO, sid):
                kg.add_relation(skill.id, RelType.RELATED_TO, sid, source="ontology")


def _month(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    return text[:7] if re.match(r"\d{4}", text) else None


def _parse_month(value: Any) -> date | None:
    match = re.match(r"(\d{4})(?:-(\d{2}))?", str(value or ""))
    return date(int(match.group(1)), int(match.group(2) or 1), 1) if match else None


def role_years(role: EntityNode) -> float:
    start = _parse_month(role.props.get("start"))
    end = _parse_month(role.props.get("end")) or date.today()
    if start is None:
        return 0.5
    return max(0.1, (end.year - start.year) + (end.month - start.month + 1) / 12)


def compute_skill_evidence(kg: KnowledgeGraph, person_id: str) -> None:
    """Derive (Person)-[:HAS_SKILL {strength, years, evidence}]->(Skill) from the evidence graph.

    Professional use weighs most (and grows with tenure), then shipped projects
    (capped), then being listed on the CV and being verified in source code.
    """
    roles: dict[str, set[str]] = defaultdict(set)
    projects: dict[str, set[str]] = defaultdict(set)
    for rel in kg.relations:
        if rel.type == RelType.USED:
            roles[rel.target].add(rel.source)
        elif rel.type == RelType.USES:
            projects[rel.target].add(rel.source)
    verified = {e.id for e in kg.entities.values() if e.props.get("verified_in_code")}
    for skill in [e for e in kg.entities.values() if e.type == NodeType.SKILL]:
        role_ids, project_ids = roles[skill.id], projects[skill.id]
        listed = bool(skill.props.get("listed_on_cv"))
        years = sum(role_years(kg.entities[r]) for r in role_ids)
        strength = min(
            1.0,
            sum(0.35 + 0.1 * min(role_years(kg.entities[r]), 4) for r in role_ids)
            + min(0.45, 0.15 * len(project_ids))
            + (0.12 if listed else 0)
            + (0.08 if skill.id in verified else 0),
        )
        if strength <= 0:
            continue
        dates: list[str] = []
        for rid in role_ids:
            role = kg.entities[rid]
            dates.append("9999" if role.props.get("current") else (_month(role.props.get("end")) or ""))
        for pid in project_ids:
            project = kg.entities[pid]
            dates.append(_month(project.props.get("pushed_at")) or _month(project.props.get("period")) or "")
        last = max((d for d in dates if d), default=None)
        last_used = "present" if last == "9999" else last
        evidence = len(role_ids) + len(project_ids)
        kg.add_relation(
            person_id,
            RelType.HAS_SKILL,
            skill.id,
            strength=round(strength, 2),
            evidence=evidence,
            listed=listed,
            verified=skill.id in verified,
            last_used=last_used,
            years=round(years, 1),
        )
        skill.props.update(
            {
                "strength": round(strength, 2),
                "evidence": evidence,
                "last_used": last_used,
                "years": round(years, 1),
            }
        )
        role_names = sorted(kg.entities[r].name for r in role_ids)
        project_names = sorted(kg.entities[p].name for p in project_ids)
        parts = [f"{skill.name} ({skill.props.get('category', 'skill')})."]
        if role_names:
            parts.append(f"Used professionally (~{years:.1f} years) as: {'; '.join(role_names)}.")
        if project_names:
            parts.append(f"Used in projects: {'; '.join(project_names)}.")
        if skill.id in verified:
            parts.append("Verified in source code / manifests on GitHub.")
        if listed:
            parts.append("Listed on the CV.")
        skill.description = " ".join(parts)


class MentionMatcher:
    """Finds entity names in text: long names case-insensitively, short ones (Go, Nx, PWA) exactly."""

    def __init__(self, kg: KnowledgeGraph) -> None:
        self.insensitive: dict[str, str] = {}
        self.sensitive: dict[str, str] = {}
        for node_type in (
            NodeType.SKILL,
            NodeType.PROJECT,
            NodeType.ORGANIZATION,
            NodeType.AWARD,
            NodeType.LOCATION,
        ):
            for entity in kg.entities.values():
                if entity.type != node_type:
                    continue
                aliases = [a for a in {*entity.aliases, *all_aliases(entity.name)} if _distinctive(a)]
                for label in [entity.name, *aliases]:
                    if len(label) >= 4:
                        self.insensitive.setdefault(label.lower(), entity.id)
                    elif len(label) >= 2:
                        self.sensitive.setdefault(label, entity.id)
        self._insensitive_re = self._compile(self.insensitive, re.IGNORECASE)
        self._sensitive_re = self._compile(self.sensitive, 0)

    @staticmethod
    def _compile(terms: dict[str, str], flags: int) -> re.Pattern[str] | None:
        if not terms:
            return None
        body = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
        return re.compile(rf"(?<![\w.-])(?:{body})(?![\w-])", flags)

    def find(self, text: str) -> set[str]:
        found: set[str] = set()
        if self._insensitive_re:
            found.update(self.insensitive[m.group(0).lower()] for m in self._insensitive_re.finditer(text))
        if self._sensitive_re:
            found.update(self.sensitive[m.group(0)] for m in self._sensitive_re.finditer(text))
        return found


def _distinctive(alias: str) -> bool:
    return len(alias) >= 6 and (bool(re.search(r"[\d.\-+#/ ]", alias)) or alias[0].isupper())


def build_chunks(kg: KnowledgeGraph, docs: Sequence[SourceDoc]) -> None:
    matcher = MentionMatcher(kg)
    for doc in docs:
        kg.documents.append(doc.node)
        for chunk in chunk_markdown(doc.text, doc_title=doc.node.title):
            mentions = set(doc.node.describes) | matcher.find(chunk.text)
            kg.chunks.append(
                ChunkNode(
                    id=f"{doc.node.id}#{chunk.ord}",
                    doc_id=doc.node.id,
                    title=chunk.title,
                    text=chunk.text,
                    ord=chunk.ord,
                    mentions=sorted(m for m in mentions if m in kg.entities),
                )
            )


# ── communities (GraphRAG "global" layer) ────────────────────────────────────
async def build_communities(kg: KnowledgeGraph, llm: Gemini, cache: KVCache, settings: Settings) -> None:
    graph = nx.Graph()
    for entity in kg.entities.values():
        if entity.type not in COMMUNITY_EXCLUDED:
            graph.add_node(entity.id)
    for rel in kg.relations:
        weight = PPR_EDGE_WEIGHTS.get(rel.type, 0.0)
        if weight > 0 and graph.has_node(rel.source) and graph.has_node(rel.target):
            previous = graph.get_edge_data(rel.source, rel.target, {}).get("weight", 0.0)
            graph.add_edge(rel.source, rel.target, weight=previous + weight)
    graph.remove_nodes_from([n for n in list(graph.nodes) if graph.degree(n) == 0])
    if graph.number_of_nodes() < 3:
        return
    partitions = nx.community.louvain_communities(graph, weight="weight", resolution=1.1, seed=7)
    groups = sorted((sorted(p) for p in partitions if len(p) >= 3), key=len, reverse=True)[:12]

    async def summarize(members: list[str]) -> CommunityNode:
        ranked = sorted(members, key=lambda m: -graph.degree(m, weight="weight"))
        lines = [
            f"- {kg.entities[m].type.value}: {kg.entities[m].name} — {truncate(kg.entities[m].description, 160)}"
            for m in ranked[:40]
        ]
        member_set = set(members)
        triples = [
            f"- {kg.entities[r.source].name} —{r.type.value}→ {kg.entities[r.target].name}"
            for r in kg.relations
            if r.source in member_set and r.target in member_set
        ][:60]
        description = "Entities:\n" + "\n".join(lines) + "\n\nRelations:\n" + "\n".join(triples)
        report = await summarize_community(
            llm, cache, models=list(settings.extraction_models), description=description, members=members
        )
        cid = "community:" + hashlib.sha1("|".join(sorted(members)).encode()).hexdigest()[:10]
        if report is None:
            names = [kg.entities[m].name for m in ranked[:4]]
            return CommunityNode(
                id=cid,
                title=" · ".join(names[:3]),
                summary=f"Cluster around {', '.join(names)}.",
                members=members,
                key_entities=names,
            )
        return CommunityNode(
            id=cid,
            title=report.title,
            summary=report.summary,
            members=members,
            key_entities=report.key_entities[:6],
        )

    limit = asyncio.Semaphore(2)

    async def bounded(members: list[str]) -> CommunityNode:
        async with limit:
            return await summarize(members)

    kg.communities = list(await asyncio.gather(*(bounded(g) for g in groups)))


def compute_pagerank(kg: KnowledgeGraph) -> None:
    snapshot = GraphSnapshot(
        "build",
        [EntityView(id=e.id, type=e.type.value, name=e.name) for e in kg.entities.values()],
        [EdgeView(source=r.source, target=r.target, type=r.type.value) for r in kg.relations],
    )
    ranks = snapshot.global_pagerank()
    top = max(ranks.values(), default=1.0)
    for entity in kg.entities.values():
        rank = ranks.get(entity.id, 0.0)
        entity.props["pagerank"] = round(top * 1.6 if entity.type == NodeType.PERSON else rank, 6)


# ── embeddings ───────────────────────────────────────────────────────────────
async def embed_texts(
    llm: Gemini, cache: KVCache, settings: Settings, texts: Sequence[str], task: EmbedTask
) -> list[list[float]]:
    keys = [content_key("emb", settings.embedding_model, settings.embedding_dim, task, t) for t in texts]
    found = cache.get_vectors(keys)
    missing = [i for i, k in enumerate(keys) if k not in found]
    if missing:
        vectors = await llm.embed([texts[i] for i in missing], task, patience_s=240)
        fresh = {keys[i]: v for i, v in zip(missing, vectors, strict=True)}
        cache.put_vectors(fresh.items())
        found.update(fresh)
    return [found[k] for k in keys]


async def embed_graph(kg: KnowledgeGraph, llm: Gemini, cache: KVCache, settings: Settings) -> None:
    if not llm.enabled:
        return
    entities = list(kg.entities.values())
    entity_vectors = await embed_texts(
        llm, cache, settings, [e.embedding_text() for e in entities], "RETRIEVAL_DOCUMENT"
    )
    for entity, vector in zip(entities, entity_vectors, strict=True):
        entity.embedding = vector
    titles = {d.id: d.title for d in kg.documents}
    chunk_texts = [f"{titles.get(c.doc_id, '')} › {c.title}\n{c.text}" for c in kg.chunks]
    chunk_vectors = await embed_texts(llm, cache, settings, chunk_texts, "RETRIEVAL_DOCUMENT")
    for chunk, vector in zip(kg.chunks, chunk_vectors, strict=True):
        chunk.embedding = vector
    if kg.communities:
        community_vectors = await embed_texts(
            llm, cache, settings, [f"{c.title}: {c.summary}" for c in kg.communities], "RETRIEVAL_DOCUMENT"
        )
        for community, vector in zip(kg.communities, community_vectors, strict=True):
            community.embedding = vector


def profile_revision(settings: Settings) -> str:
    """Hash of the curated sources: answers cached for a revision stay valid until it changes."""
    digest = hashlib.sha256(settings.profile_path.read_bytes())
    if settings.notes_dir.is_dir():
        for path in sorted(settings.notes_dir.glob("*.md")):
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def graph_version(kg: KnowledgeGraph) -> str:
    """Content hash of the graph (embeddings excluded) — identical inputs ⇒ identical version."""
    payload = {
        "entities": sorted(
            (
                e.id,
                e.name,
                e.description,
                sorted(e.aliases),
                orjson.dumps(e.props, option=orjson.OPT_SORT_KEYS).decode(),
            )
            for e in kg.entities.values()
        ),
        "relations": sorted((r.source, r.type.value, r.target) for r in kg.relations),
        "chunks": sorted((c.id, c.text, tuple(c.mentions)) for c in kg.chunks),
        "communities": sorted((c.id, c.title, c.summary) for c in kg.communities),
    }
    return hashlib.sha256(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)).hexdigest()[:12]
