"""Hybrid GraphRAG retrieval.

1. Dense (Gemini embeddings → Neo4j vector indexes) and sparse (Lucene full-text)
   search over entities and evidence chunks, fused with Reciprocal Rank Fusion.
2. Entity linking of planner hints against the in-memory graph (aliases aware).
3. HippoRAG-style Personalized PageRank seeded with those entities: multi-hop
   evidence (e.g. skill → project → role) surfaces even when it shares no words
   with the question.
4. Passages are re-ranked by fusing their lexical/semantic score with the PPR
   mass of the entities they mention; community reports are added for broad
   questions (GraphRAG "global search").
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from careergraph.graph.schema import NodeType
from careergraph.graph.snapshot import EdgeView, GraphSnapshot
from careergraph.graph.store import Neo4jStore
from careergraph.llm.gemini import Gemini, LLMUnavailableError
from careergraph.logs import get_logger
from careergraph.text import STOPWORDS

log = get_logger(__name__)

RRF_K = 60
SourceKind = Literal["passage", "entity", "community"]


@dataclass(slots=True)
class Source:
    ref: int
    kind: SourceKind
    id: str
    title: str
    text: str
    url: str | None = None
    doc_kind: str | None = None
    entity_ids: list[str] = field(default_factory=list)

    def public(self, snippet_chars: int = 320) -> dict[str, Any]:
        snippet = " ".join(self.text.split())
        if len(snippet) > snippet_chars:
            snippet = snippet[: snippet_chars - 1].rsplit(" ", 1)[0] + "…"
        return {
            "ref": self.ref,
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "snippet": snippet,
            "url": self.url,
            "docKind": self.doc_kind,
            "entityIds": self.entity_ids[:12],
        }


@dataclass
class RetrievalResult:
    queries: list[str]
    seeds: dict[str, float]
    ranked_entities: list[tuple[str, float]]
    focus: list[str]
    edges: list[EdgeView]
    sources: list[Source]
    timings_ms: dict[str, float] = field(default_factory=dict)
    degraded: bool = False

    def source_by_ref(self) -> dict[int, Source]:
        return {s.ref: s for s in self.sources}

    def graph_payload(self, snapshot: GraphSnapshot, emphasis: Iterable[str] = ()) -> dict[str, Any]:
        focus = [eid for eid in self.focus if eid in snapshot.entities]
        return {
            "nodes": focus,
            "links": [{"source": e.source, "target": e.target, "type": e.type} for e in self.edges],
            "seeds": [eid for eid in self.seeds if eid in snapshot.entities][:8],
            "emphasis": [eid for eid in emphasis if eid in snapshot.entities],
        }


def rrf(rankings: Iterable[Sequence[tuple[str, float]]], k: int = RRF_K) -> dict[str, float]:
    fused: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, (item_id, _) in enumerate(ranking):
            fused[item_id] += 1.0 / (k + rank + 1)
    return dict(fused)


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    top = max(scores.values())
    return {k: v / top for k, v in scores.items()} if top > 0 else scores


class HybridRetriever:
    def __init__(self, store: Neo4jStore, llm: Gemini, snapshot: Callable[[], GraphSnapshot]) -> None:
        self.store = store
        self.llm = llm
        self._snapshot = snapshot

    @property
    def snapshot(self) -> GraphSnapshot:
        return self._snapshot()

    async def retrieve(
        self,
        queries: Sequence[str],
        entity_hints: Sequence[str] = (),
        *,
        include_communities: bool = False,
        k_chunks: int = 8,
        k_entities: int = 10,
        query_vectors: Sequence[Sequence[float]] | None = None,
    ) -> RetrievalResult:
        started = time.perf_counter()
        timings: dict[str, float] = {}
        snapshot = self.snapshot
        queries = [q.strip() for q in queries if q and q.strip()][:4] or ["Dorian Lovichi"]
        degraded = False

        vectors: Sequence[Sequence[float]] = query_vectors or []
        if not vectors and self.llm.enabled:
            try:
                vectors = await self.llm.embed(list(queries), "RETRIEVAL_QUERY")
            except LLMUnavailableError as exc:
                log.warning("retrieval.embedding_unavailable", error=str(exc))
                degraded = True
        timings["embed"] = _ms(started)

        # 1) dense + sparse candidate generation, all lists in parallel
        t = time.perf_counter()
        tasks: list[Any] = []
        for query in queries:
            tasks.append(self.store.fulltext_search("entity_fulltext", query, 12))
            tasks.append(self.store.fulltext_search("chunk_fulltext", query, 12))
        for vector in vectors:
            tasks.append(self.store.vector_search("entity_embedding", vector, 12))
            tasks.append(self.store.vector_search("chunk_embedding", vector, 12))
            if include_communities:
                tasks.append(self.store.vector_search("community_embedding", vector, 3))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        entity_lists: list[list[tuple[str, float]]] = []
        chunk_lists: list[list[tuple[str, float]]] = []
        community_lists: list[list[tuple[str, float]]] = []
        idx = 0
        for _ in queries:
            entity_lists.append(_ok(results[idx]))
            chunk_lists.append(_ok(results[idx + 1]))
            idx += 2
        for _ in vectors:
            entity_lists.append(_dense_filter(_ok(results[idx]), 0.55))
            chunk_lists.append(_dense_filter(_ok(results[idx + 1]), 0.5))
            idx += 2
            if include_communities:
                community_lists.append(_ok(results[idx]))
                idx += 1
        timings["search"] = _ms(t)

        entity_rrf = {eid: s for eid, s in rrf(entity_lists).items() if eid in snapshot.entities}
        chunk_rrf = rrf(chunk_lists)

        # 2) seeds = fused entity hits + explicit entity links from the planner
        seeds: dict[str, float] = dict(_normalize_scores(entity_rrf))
        for hint in entity_hints:
            if linked := snapshot.lookup(hint):
                seeds[linked] = seeds.get(linked, 0.0) + 1.5
        for query in queries:  # exact mentions of known names inside the question
            for linked in _mentioned_entities(snapshot, query):
                seeds[linked] = seeds.get(linked, 0.0) + 1.0
        # entities mentioned by the best passages are weaker seeds
        for chunk_id, score in sorted(chunk_rrf.items(), key=lambda kv: -kv[1])[:4]:
            for eid in self._chunk_entities(snapshot).get(chunk_id, []):
                seeds[eid] = seeds.get(eid, 0.0) + 0.25 * score * RRF_K
        seeds = dict(sorted(seeds.items(), key=lambda kv: -kv[1])[:12])

        # 3) Personalized PageRank for multi-hop expansion
        t = time.perf_counter()
        ppr = snapshot.personalized_pagerank(seeds) if seeds else {}
        timings["ppr"] = _ms(t)
        ranked = [
            (eid, score) for eid, score in ppr.items() if snapshot.entities[eid].type != NodeType.PERSON
        ][: k_entities * 2]
        focus = [eid for eid, _ in ranked[:k_entities]]
        for eid in seeds:
            if eid not in focus and snapshot.entities[eid].type != NodeType.PERSON:
                focus.append(eid)
        focus = focus[: k_entities + 4]

        # 4) passage re-ranking: lexical/semantic RRF ⊕ PPR mass of mentioned entities
        chunk_entities = self._chunk_entities(snapshot)
        candidates = set(chunk_rrf)
        for eid in focus[:6]:
            candidates.update(snapshot.entity_chunks.get(eid, [])[:6])
        ppr_mass = {cid: sum(ppr.get(e, 0.0) for e in chunk_entities.get(cid, [])) for cid in candidates}
        rrf_norm, ppr_norm = (
            _normalize_scores({c: chunk_rrf.get(c, 0.0) for c in candidates}),
            _normalize_scores(ppr_mass),
        )
        chunk_scores = {c: 0.6 * rrf_norm.get(c, 0.0) + 0.4 * ppr_norm.get(c, 0.0) for c in candidates}
        top_chunks = [c for c, _ in sorted(chunk_scores.items(), key=lambda kv: -kv[1])[:k_chunks]]

        t = time.perf_counter()
        chunk_rows = await self.store.chunks_by_ids(top_chunks) if top_chunks else []
        community_ids = [cid for cid, _ in sorted(rrf(community_lists).items(), key=lambda kv: -kv[1])[:3]]
        community_rows = await self.store.communities_by_ids(community_ids) if community_ids else []
        timings["fetch"] = _ms(t)

        # 5) assemble numbered sources: passages, then entity cards, then community reports
        order = {cid: i for i, cid in enumerate(top_chunks)}
        chunk_rows.sort(key=lambda row: order.get(row["id"], 99))
        sources: list[Source] = []
        for row in chunk_rows:
            sources.append(
                Source(
                    ref=len(sources) + 1,
                    kind="passage",
                    id=row["id"],
                    title=_passage_title(row),
                    text=row["text"],
                    url=row.get("url"),
                    doc_kind=row.get("kind"),
                    entity_ids=list(row.get("mentions") or []),
                )
            )
        for eid in focus[:k_entities]:
            entity = snapshot.entities[eid]
            sources.append(
                Source(
                    ref=len(sources) + 1,
                    kind="entity",
                    id=eid,
                    title=f"{entity.type}: {entity.name}",
                    text=self._entity_card(snapshot, eid),
                    url=entity.url,
                    doc_kind="graph",
                    entity_ids=[eid],
                )
            )
        for row in community_rows:
            sources.append(
                Source(
                    ref=len(sources) + 1,
                    kind="community",
                    id=row["id"],
                    title=f"Theme: {row['title']}",
                    text=row["summary"],
                    doc_kind="community",
                )
            )

        edges = snapshot.edges_within(focus)
        timings["total"] = _ms(started)
        return RetrievalResult(
            queries=list(queries),
            seeds=seeds,
            ranked_entities=ranked,
            focus=focus,
            edges=edges,
            sources=sources,
            timings_ms=timings,
            degraded=degraded,
        )

    # ── helpers ───────────────────────────────────────────────────────────────
    _chunk_index_cache: tuple[str, dict[str, list[str]]] | None = None

    def _chunk_entities(self, snapshot: GraphSnapshot) -> dict[str, list[str]]:
        cached = self._chunk_index_cache
        if cached is not None and cached[0] == snapshot.version:
            return cached[1]
        index: dict[str, list[str]] = defaultdict(list)
        for eid, chunk_ids in snapshot.entity_chunks.items():
            for cid in chunk_ids:
                index[cid].append(eid)
        self._chunk_index_cache = (snapshot.version, dict(index))
        return self._chunk_index_cache[1]

    @staticmethod
    def _entity_card(snapshot: GraphSnapshot, entity_id: str, max_relations: int = 14) -> str:
        entity = snapshot.entities[entity_id]
        lines = [f"{entity.type} «{entity.name}»"]
        if entity.description:
            lines.append(entity.description[:500])
        details = entity.summary()
        extras = {k: v for k, v in details.items() if k not in {"id", "type", "name", "description", "url"}}
        if extras:
            lines.append("; ".join(f"{k}: {v}" for k, v in extras.items()))
        highlights = entity.props.get("highlights")
        if isinstance(highlights, list) and highlights:
            lines.extend(f"• {h}" for h in highlights[:4])
        relations = []
        for edge, direction, other_id in snapshot.neighbors(entity_id):
            other = snapshot.entities[other_id]
            if other.type == NodeType.PERSON and edge.type == "HAS_SKILL":
                strength = edge.props.get("strength")
                relations.append(f"Dorian has this skill (evidence strength {strength})")
                continue
            arrow = f"—{edge.type}→ {other.name}" if direction == "out" else f"←{edge.type}— {other.name}"
            relations.append(f"{arrow} ({other.type})")
        if relations:
            lines.append("Relations: " + "; ".join(relations[:max_relations]))
        return "\n".join(lines)


def _ok(result: Any) -> list[tuple[str, float]]:
    if isinstance(result, BaseException):
        log.warning("retrieval.search_failed", error=str(result)[:200])
        return []
    return list(result)


def _dense_filter(hits: list[tuple[str, float]], min_score: float) -> list[tuple[str, float]]:
    """Neo4j cosine scores are in [0, 1]; drop hits that are clearly unrelated."""
    return [(item, score) for item, score in hits if score >= min_score]


def _mentioned_entities(snapshot: GraphSnapshot, text: str) -> list[str]:
    words = [w for w in text.replace("?", " ").replace(",", " ").split() if w]
    found: list[str] = []
    for size in (4, 3, 2, 1):
        for i in range(len(words) - size + 1):
            candidate = " ".join(words[i : i + size])
            if len(candidate) < 2 or (size == 1 and candidate.lower() in STOPWORDS):
                continue
            if (eid := snapshot.lookup(candidate)) and eid not in found:
                entity = snapshot.entities[eid]
                if entity.type != NodeType.PERSON:
                    found.append(eid)
    return found[:8]


def _passage_title(row: dict[str, Any]) -> str:
    doc_title = row.get("doc_title") or "Document"
    section = row.get("title") or ""
    return f"{doc_title} › {section}" if section and section != doc_title else doc_title


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)
