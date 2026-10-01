"""Entity resolution helpers: canonical IDs, skill normalisation and duplicate merging."""

from __future__ import annotations

import re
from collections.abc import Sequence

import numpy as np

from careergraph.graph.models import EntityNode, KnowledgeGraph
from careergraph.graph.schema import NodeType, RelType
from careergraph.graph.snapshot import normalize_name
from careergraph.ingest.techmap import GENERIC_SKILLS, all_aliases, canonical
from careergraph.logs import get_logger
from careergraph.text import slugify

log = get_logger(__name__)

_NOISE = re.compile(r"\s*\((?:optional|coming soon|planned|future)\)\s*$", re.I)


def clean_skill_name(name: str) -> str:
    name = _NOISE.sub("", name.strip().strip("•-*`\"'"))
    return re.sub(r"\s+", " ", name)


def skill_id(display_name: str) -> str:
    return f"skill:{slugify(display_name)}"


def add_skill(
    kg: KnowledgeGraph,
    name: str,
    *,
    source: str,
    category: str | None = None,
    domain: str | None = None,
    description: str = "",
) -> str | None:
    """Resolve ``name`` to a canonical Skill node (creating it if needed) and return its id."""
    raw = clean_skill_name(name)
    if not raw or len(raw) > 60 or normalize_name(raw) in GENERIC_SKILLS:
        return None
    tech = canonical(raw)
    display = tech.name if tech else raw
    sid = skill_id(display)
    aliases = all_aliases(display) if tech else []
    if raw != display:
        aliases.append(raw)
    existing = kg.entities.get(sid)
    if existing is None:
        # Fall back to a normalised-name match against skills already in the graph.
        key = normalize_name(display)
        for entity in kg.entities.values():
            if entity.type == NodeType.SKILL and key in {
                normalize_name(entity.name),
                *map(normalize_name, entity.aliases),
            }:
                existing = entity
                sid = entity.id
                break
    node = EntityNode(
        id=sid,
        type=NodeType.SKILL,
        name=existing.name if existing else display,
        description=description,
        aliases=aliases,
        props={
            "category": tech.category if tech else (category or "concept"),
            "domain": tech.domain if tech else (domain or ""),
            "known": tech is not None,
        },
        sources=[source],
    )
    kg.add_entity(node)
    return sid


def link_domains(kg: KnowledgeGraph) -> None:
    """Attach every skill to its domain (CV skill group or ontology domain)."""
    for entity in list(kg.entities.values()):
        if entity.type != NodeType.SKILL:
            continue
        domain = str(entity.props.get("domain") or "")
        if not domain:
            continue
        did = f"domain:{slugify(domain)}"
        if did not in kg.entities:
            kg.add_entity(
                EntityNode(id=did, type=NodeType.DOMAIN, name=domain, description=f"Skill domain: {domain}")
            )
        if not any(r.source == entity.id and r.type == RelType.IN_DOMAIN for r in kg.relations):
            kg.add_relation(entity.id, RelType.IN_DOMAIN, did)


def merge_entities(kg: KnowledgeGraph, keep: str, drop: str) -> None:
    """Merge ``drop`` into ``keep``: aliases, sources and every relation are re-pointed."""
    if keep == drop or keep not in kg.entities or drop not in kg.entities:
        return
    dropped = kg.entities.pop(drop)
    target = kg.entities[keep]
    target.aliases = sorted({*target.aliases, dropped.name, *dropped.aliases} - {target.name})
    target.sources = sorted({*target.sources, *dropped.sources})
    if len(dropped.description) > len(target.description):
        target.description = dropped.description
    old = kg.relations
    kg.relations = []
    kg._relation_index.clear()
    for relation in old:
        source = keep if relation.source == drop else relation.source
        target_id = keep if relation.target == drop else relation.target
        kg.add_relation(source, relation.type, target_id, **relation.props)
    for chunk in kg.chunks:
        chunk.mentions = sorted({keep if m == drop else m for m in chunk.mentions})
    for doc in kg.documents:
        doc.describes = sorted({keep if d == drop else d for d in doc.describes})


def merge_similar_skills(
    kg: KnowledgeGraph, ids: Sequence[str], vectors: Sequence[Sequence[float]], threshold: float = 0.95
) -> int:
    """Embedding-based dedup of skills the ontology does not know (e.g. 'Offline sync' ≈ 'Offline-first')."""
    if len(ids) < 2:
        return 0
    matrix = np.asarray(vectors, dtype=np.float32)
    sims = matrix @ matrix.T
    merged = 0
    alive = set(ids)
    for i, a in enumerate(ids):
        for j in range(i + 1, len(ids)):
            b = ids[j]
            if a not in alive or b not in alive or sims[i, j] < threshold:
                continue
            ea, eb = kg.entities.get(a), kg.entities.get(b)
            if ea is None or eb is None:
                continue
            # Never merge two technologies the ontology knows as distinct (React vs React Native).
            if ea.props.get("known") and eb.props.get("known"):
                continue
            keep, drop = (a, b) if (ea.props.get("known") or len(ea.sources) >= len(eb.sources)) else (b, a)
            log.info(
                "resolve.merge",
                keep=kg.entities[keep].name,
                drop=kg.entities[drop].name,
                sim=round(float(sims[i, j]), 3),
            )
            merge_entities(kg, keep, drop)
            alive.discard(drop)
            merged += 1
    return merged
