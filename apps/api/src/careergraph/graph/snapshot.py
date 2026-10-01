"""Read-optimised, in-process copy of the entity graph.

The career graph is small (hundreds of nodes), so every API replica keeps a
snapshot in memory and refreshes it when the ingestion job bumps the graph
version. This makes Personalized PageRank, path finding and name lookup
sub-millisecond, while Neo4j remains the system of record (vector + full-text
indexes, Cypher).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from careergraph.graph.schema import PPR_EDGE_WEIGHTS, NodeType


def normalize_name(text: str) -> str:
    """Case/accent/punctuation-insensitive key: 'Node.js' → 'nodejs', 'CI/CD' → 'cicd'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().replace("++", "pp").replace("#", "sharp")
    return re.sub(r"[^a-z0-9]+", "", text)


@dataclass(slots=True)
class EntityView:
    id: str
    type: str
    name: str
    description: str = ""
    url: str | None = None
    aliases: list[str] = field(default_factory=list)
    pagerank: float = 0.0
    community: str | None = None
    props: dict[str, Any] = field(default_factory=dict)

    def summary(self, max_chars: int = 400) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "type": self.type, "name": self.name}
        if self.description:
            data["description"] = self.description[:max_chars]
        if self.url:
            data["url"] = self.url
        for key in ("category", "start", "end", "period", "level", "honors", "school", "year", "stars"):
            if self.props.get(key) not in (None, "", []):
                data[key] = self.props[key]
        return data


@dataclass(slots=True)
class EdgeView:
    source: str
    target: str
    type: str
    props: dict[str, Any] = field(default_factory=dict)


class GraphSnapshot:
    def __init__(
        self,
        version: str,
        entities: Iterable[EntityView],
        edges: Iterable[EdgeView],
        entity_chunks: Mapping[str, list[str]] | None = None,
    ) -> None:
        self.version = version
        self.entities: dict[str, EntityView] = {e.id: e for e in entities}
        self.edges: list[EdgeView] = [
            e for e in edges if e.source in self.entities and e.target in self.entities
        ]
        self.entity_chunks: dict[str, list[str]] = dict(entity_chunks or {})
        self.ids: list[str] = list(self.entities)
        self.index: dict[str, int] = {eid: i for i, eid in enumerate(self.ids)}
        self._out: dict[str, list[EdgeView]] = defaultdict(list)
        self._in: dict[str, list[EdgeView]] = defaultdict(list)
        for edge in self.edges:
            self._out[edge.source].append(edge)
            self._in[edge.target].append(edge)
        self._names: dict[str, str] = {}
        for entity in sorted(self.entities.values(), key=lambda e: _type_priority(e.type)):
            for label in [entity.name, *entity.aliases]:
                self._names.setdefault(normalize_name(label), entity.id)
        self._build_transition()

    # ── construction helpers ──────────────────────────────────────────────────
    def _build_transition(self) -> None:
        """Undirected weighted edge list (Person excluded) for random walks."""
        person_ids = {e.id for e in self.entities.values() if e.type == NodeType.PERSON}
        src, dst, weight = [], [], []
        for edge in self.edges:
            w = PPR_EDGE_WEIGHTS.get(edge.type, 0.0)
            if w <= 0 or edge.source in person_ids or edge.target in person_ids:
                continue
            a, b = self.index[edge.source], self.index[edge.target]
            src += [a, b]
            dst += [b, a]
            weight += [w, w]
        n = len(self.ids)
        self._src = np.asarray(src, dtype=np.int64)
        self._dst = np.asarray(dst, dtype=np.int64)
        w_arr = np.asarray(weight, dtype=np.float64)
        out_weight = np.bincount(self._src, weights=w_arr, minlength=n) if n else np.zeros(0)
        with np.errstate(divide="ignore", invalid="ignore"):
            self._w_norm = w_arr / out_weight[self._src] if len(w_arr) else w_arr
        self._dangling = out_weight == 0

    # ── algorithms ────────────────────────────────────────────────────────────
    def personalized_pagerank(
        self, seeds: Mapping[str, float], *, damping: float = 0.5, iterations: int = 60, tol: float = 1e-9
    ) -> dict[str, float]:
        """HippoRAG-style PPR: random walk with restart to the query's seed entities."""
        n = len(self.ids)
        if n == 0:
            return {}
        restart = np.zeros(n)
        for entity_id, weight in seeds.items():
            if entity_id in self.index and weight > 0:
                restart[self.index[entity_id]] += weight
        if restart.sum() == 0:
            restart[:] = 1.0
        restart /= restart.sum()
        rank = restart.copy()
        for _ in range(iterations):
            flow = np.bincount(self._dst, weights=rank[self._src] * self._w_norm, minlength=n)
            dangling_mass = rank[self._dangling].sum()
            new_rank = (1 - damping) * restart + damping * (flow + dangling_mass * restart)
            if np.abs(new_rank - rank).sum() < tol:
                rank = new_rank
                break
            rank = new_rank
        return {self.ids[i]: float(rank[i]) for i in np.argsort(-rank) if rank[i] > 0}

    def global_pagerank(self) -> dict[str, float]:
        return self.personalized_pagerank({}, damping=0.85)

    def lookup(self, name: str) -> str | None:
        key = normalize_name(name)
        if not key:
            return None
        if key in self._names:
            return self._names[key]
        # Tolerate plural/singular differences ("LLM" vs "LLMs") without mapping "css" to "c".
        candidates = [f"{key}s"]
        if key.endswith("s") and len(key) > 3:
            candidates.append(key[:-1])
        for candidate in candidates:
            if candidate in self._names:
                return self._names[candidate]
        return None

    def neighbors(self, entity_id: str) -> list[tuple[EdgeView, str, str]]:
        """(edge, direction, other_id) for every relation touching ``entity_id``."""
        out = [(edge, "out", edge.target) for edge in self._out.get(entity_id, [])]
        inbound = [(edge, "in", edge.source) for edge in self._in.get(entity_id, [])]
        return out + inbound

    def edges_within(self, ids: Iterable[str]) -> list[EdgeView]:
        wanted = set(ids)
        return [edge for edge in self.edges if edge.source in wanted and edge.target in wanted]

    def shortest_path(self, source: str, target: str, *, max_depth: int = 6) -> list[str]:
        """Undirected BFS that avoids hub nodes (Person/Domain) as intermediate hops."""
        if source not in self.entities or target not in self.entities:
            return []
        hubs = {e.id for e in self.entities.values() if e.type in (NodeType.PERSON, NodeType.DOMAIN)}
        parents: dict[str, str | None] = {source: None}
        queue = deque([(source, 0)])
        while queue:
            node, depth = queue.popleft()
            if node == target:
                path = [node]
                while (parent := parents[path[-1]]) is not None:
                    path.append(parent)
                return path[::-1]
            if depth >= max_depth or (node in hubs and node != source):
                continue
            for _, _, other in self.neighbors(node):
                if other not in parents:
                    parents[other] = node
                    queue.append((other, depth + 1))
        return []

    def by_type(self, *types: str) -> list[EntityView]:
        return [e for e in self.entities.values() if e.type in types]

    def to_view_graph(self) -> dict[str, Any]:
        """Payload for the 3D visualisation (no evidence text, no embeddings)."""
        degree: dict[str, int] = defaultdict(int)
        for edge in self.edges:
            degree[edge.source] += 1
            degree[edge.target] += 1
        nodes = []
        for entity in self.entities.values():
            node: dict[str, Any] = {
                "id": entity.id,
                "name": entity.name,
                "type": entity.type,
                "pagerank": round(entity.pagerank, 6),
                "degree": degree[entity.id],
                "community": entity.community,
            }
            for key in ("category", "domain", "featured", "start", "end", "period", "strength", "minor"):
                if entity.props.get(key) not in (None, "", []):
                    node[key] = entity.props[key]
            nodes.append(node)
        links = [{"source": e.source, "target": e.target, "type": e.type} for e in self.edges]
        return {"version": self.version, "nodes": nodes, "links": links}

    @classmethod
    def from_rows(cls, version: str, rows: Mapping[str, list[dict[str, Any]]]) -> GraphSnapshot:
        reserved = {"id", "type", "name", "description", "url", "aliases", "pagerank", "community", "sources"}
        entities = [
            EntityView(
                id=row["id"],
                type=row.get("type") or "Entity",
                name=row.get("name") or row["id"],
                description=row.get("description") or "",
                url=row.get("url"),
                aliases=list(row.get("aliases") or []),
                pagerank=float(row.get("pagerank") or 0.0),
                community=row.get("community"),
                props={k: v for k, v in row.items() if k not in reserved and v is not None},
            )
            for row in rows.get("entities", [])
        ]
        edges = [
            EdgeView(source=r["source"], target=r["target"], type=r["type"], props=dict(r.get("props") or {}))
            for r in rows.get("relations", [])
        ]
        mentions = {row["entity"]: list(row["chunks"]) for row in rows.get("mentions", [])}
        return cls(version, entities, edges, mentions)


_TYPE_PRIORITY: dict[str, int] = {
    NodeType.SKILL: 0,
    NodeType.PROJECT: 1,
    NodeType.ORGANIZATION: 2,
    NodeType.ROLE: 3,
    NodeType.DOMAIN: 4,
}


def _type_priority(node_type: str) -> int:
    return _TYPE_PRIORITY.get(node_type, 9)
