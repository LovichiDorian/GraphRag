"""Health, stats and profile endpoints."""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Request, Response

from careergraph.agent.prompts import STARTER_QUESTIONS
from careergraph.api.deps import services_of
from careergraph.graph.schema import NodeType

router = APIRouter(tags=["meta"])


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(request: Request, response: Response) -> dict[str, Any]:
    services = services_of(request)
    ready = services.neo4j_ready
    response.status_code = 200 if ready else 503
    return {"ready": ready, "graphVersion": services.snapshot().version}


@router.get("/api/stats")
async def stats(request: Request) -> dict[str, Any]:
    services = services_of(request)
    snapshot = services.snapshot()
    by_type = Counter(entity.type for entity in snapshot.entities.values())
    relations = Counter(edge.type for edge in snapshot.edges)
    meta = services.meta or {}
    built = meta.get("stats") or {}
    settings = services.settings
    return {
        "graph": {
            "version": snapshot.version,
            "builtAt": meta.get("built_at"),
            "entities": len(snapshot.entities),
            "relations": len(snapshot.edges),
            "entitiesByType": dict(by_type.most_common()),
            "relationsByType": dict(relations.most_common()),
            "documents": built.get("documents"),
            "chunks": built.get("chunks"),
            "communities": built.get("communities"),
            "repositories": built.get("repositories"),
            "ingestionSeconds": built.get("seconds"),
        },
        "models": {
            "chat": settings.chat_models,
            "fast": settings.fast_models,
            "extraction": built.get("extraction_models") or settings.extraction_models,
            "embedding": f"{settings.embedding_model} ({settings.embedding_dim}d)",
        },
        "llm": services.llm.health(),
        "cache": {"hits": services.agent.cache.hits, "misses": services.agent.cache.misses},
        "neo4j": services.neo4j_ready,
    }


@router.get("/api/profile")
async def profile(request: Request) -> dict[str, Any]:
    services = services_of(request)
    snapshot = services.snapshot()
    people = snapshot.by_type(NodeType.PERSON)
    person = people[0] if people else None
    skills: list[dict[str, Any]] = []
    if person:
        for edge, _, other_id in snapshot.neighbors(person.id):
            if edge.type == "HAS_SKILL":
                other = snapshot.entities[other_id]
                skills.append(
                    {
                        "id": other.id,
                        "name": other.name,
                        "category": other.props.get("category"),
                        "strength": edge.props.get("strength", 0),
                        "evidence": edge.props.get("evidence", 0),
                    }
                )
        skills.sort(key=lambda s: (-float(s["strength"] or 0), s["name"]))
    featured = [
        {"id": p.id, "name": p.name, "url": p.url, "summary": p.description}
        for p in snapshot.by_type(NodeType.PROJECT)
        if p.props.get("featured")
    ]
    return {
        "person": person.summary(max_chars=2000)
        | {
            k: person.props.get(k)
            for k in ("headline", "location", "email", "linkedin", "github", "website", "work_authorization")
        }
        if person
        else None,
        "topSkills": skills[:24],
        "featuredProjects": featured,
        "starterQuestions": STARTER_QUESTIONS,
    }
