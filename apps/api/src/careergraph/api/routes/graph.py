"""Read-only graph endpoints powering the 3D explorer and the command palette."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from careergraph.api.deps import services_of
from careergraph.graph.schema import NodeType
from careergraph.graph.snapshot import normalize_name

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("")
async def graph(request: Request, response: Response) -> Any:
    snapshot = services_of(request).snapshot()
    etag = f'W/"graph-{snapshot.version}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=600"
    return snapshot.to_view_graph()


@router.get("/search")
async def search(request: Request, q: str = Query(min_length=1, max_length=80), limit: int = 12) -> Any:
    snapshot = services_of(request).snapshot()
    key = normalize_name(q)
    if not key:
        return {"results": []}
    scored: list[tuple[float, dict[str, Any]]] = []
    for entity in snapshot.entities.values():
        names = [entity.name, *entity.aliases]
        keys = [normalize_name(n) for n in names]
        if any(k.startswith(key) for k in keys):
            bonus = 2.0
        elif any(key in k for k in keys):
            bonus = 1.0
        else:
            continue
        scored.append(
            (bonus + entity.pagerank * 50, {"id": entity.id, "name": entity.name, "type": entity.type})
        )
    scored.sort(key=lambda item: -item[0])
    return {"results": [item for _, item in scored[: max(1, min(limit, 30))]]}


@router.get("/path")
async def path(request: Request, source: str = Query(alias="from"), target: str = Query(alias="to")) -> Any:
    snapshot = services_of(request).snapshot()
    a = source if source in snapshot.entities else snapshot.lookup(source)
    b = target if target in snapshot.entities else snapshot.lookup(target)
    if not a or not b:
        raise HTTPException(404, "Unknown entity")
    ids = snapshot.shortest_path(a, b)
    return {
        "nodes": [snapshot.entities[i].summary() for i in ids],
        "links": [
            {"source": e.source, "target": e.target, "type": e.type} for e in snapshot.edges_within(ids)
        ],
    }


@router.get("/node/{entity_id}")
async def node(request: Request, entity_id: str) -> Any:
    services = services_of(request)
    snapshot = services.snapshot()
    entity = snapshot.entities.get(entity_id)
    if entity is None:
        raise HTTPException(404, "Unknown entity")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge, direction, other_id in snapshot.neighbors(entity_id):
        other = snapshot.entities[other_id]
        label = _relation_label(edge.type, direction, entity.type)
        item: dict[str, Any] = {"id": other.id, "name": other.name, "type": other.type}
        if edge.props:
            item["props"] = {
                k: v for k, v in edge.props.items() if k in {"strength", "evidence", "level", "source"}
            }
        grouped[label].append(item)
    for items in grouped.values():
        items.sort(key=lambda i: -snapshot.entities[i["id"]].pagerank)
    details = {
        **entity.summary(max_chars=3000),
        "aliases": entity.aliases,
        "pagerank": entity.pagerank,
        "community": entity.community,
        **{
            k: v
            for k, v in entity.props.items()
            if k in {"highlights", "headline", "location", "summary", "email", "linkedin", "github", "website",
                     "repo_url", "primary_language", "languages", "topics", "pushed_at", "strength", "evidence",
                     "last_used", "work_authorization", "organization_description"}
        },
    }  # fmt: skip
    evidence = await services.store.entity_evidence(entity_id) if services.neo4j_ready else []
    return {"entity": details, "relations": dict(grouped), "evidence": evidence}


_LABELS = {
    ("HELD_ROLE", "out"): "Roles",
    ("HELD_ROLE", "in"): "Held by",
    ("AT", "out"): "At",
    ("AT", "in"): "Roles & degrees here",
    ("BUILT", "out"): "Projects",
    ("BUILT", "in"): "Built by",
    ("DELIVERED", "out"): "Delivered projects",
    ("DELIVERED", "in"): "Delivered during",
    ("USES", "out"): "Tech stack",
    ("USES", "in"): "Used in projects",
    ("USED", "out"): "Skills used",
    ("USED", "in"): "Used in roles",
    ("HAS_SKILL", "out"): "Skills",
    ("HAS_SKILL", "in"): "Skill of",
    ("IN_DOMAIN", "out"): "Domain",
    ("IN_DOMAIN", "in"): "Skills in this domain",
    ("RELATED_TO", "out"): "Related",
    ("RELATED_TO", "in"): "Related",
    ("STUDIED", "out"): "Education",
    ("SPEAKS", "out"): "Languages",
    ("WON", "out"): "Awards",
    ("AWARDED_FOR", "out"): "For project",
    ("AWARDED_FOR", "in"): "Awards",
    ("AWARDED_BY", "out"): "Awarded by",
    ("AWARDED_BY", "in"): "Awards given",
    ("LOCATED_IN", "out"): "Location",
    ("LOCATED_IN", "in"): "Located here",
}


def _relation_label(rel_type: str, direction: str, node_type: str) -> str:
    if node_type == NodeType.PERSON and rel_type == "HAS_SKILL":
        return "Skills"
    return _LABELS.get((rel_type, direction), rel_type.replace("_", " ").title())
