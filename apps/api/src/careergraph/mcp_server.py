"""Model Context Protocol server: plug Dorian's career graph into any AI assistant.

Mounted at ``/mcp`` (Streamable HTTP, stateless, JSON responses). Example for
Claude Code: ``claude mcp add --transport http dorian https://graphrag.dorianlovichi.com/mcp``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import orjson
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from careergraph.api.ratelimit import RateLimiter
from careergraph.graph.schema import NodeType
from careergraph.services import Services
from careergraph.text import truncate

INSTRUCTIONS = """\
Tools to query the career knowledge graph of Dorian Lovichi — full-stack software engineer
(applied AI: LLMs, RAG, agents; DevOps: Docker, Kubernetes). Data comes from his CV and GitHub
repositories. Prefer `ask` for natural-language questions (grounded, cited answers),
`search_graph` / `get_entity` for raw evidence, and `assess_job_fit` to evaluate a job description."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


def build_mcp_server(get_services: Callable[[], Services]) -> MCPServer:
    server: MCPServer = MCPServer(
        name="dorian-lovichi-career-graph",
        title="Dorian Lovichi — Career Graph",
        instructions=INSTRUCTIONS,
        website_url="https://graphrag.dorianlovichi.com",
        version="1.0.0",
    )
    limiter = RateLimiter(per_minute=20, per_day=400)

    def _guard(cost: int = 1) -> None:
        if limiter.hit("mcp", cost) is not None:
            raise RuntimeError("Rate limit reached for the public MCP endpoint, retry in a minute.")

    @server.tool(annotations=READ_ONLY)
    async def ask(question: str) -> dict[str, Any]:
        """Ask a natural-language question about Dorian's experience, skills or projects.

        Returns a grounded answer with numbered citations and the cited sources.
        """
        _guard()
        return await get_services().agent.answer(truncate(question, 1500))

    @server.tool(annotations=READ_ONLY)
    async def search_graph(query: str, limit: int = 8) -> dict[str, Any]:
        """Hybrid GraphRAG retrieval (vector + full-text + Personalized PageRank) without generation.

        Returns the most relevant entities and evidence passages for `query`.
        """
        services = get_services()
        result = await services.retriever.retrieve([truncate(query, 500)], [], k_chunks=min(limit, 12))
        snapshot = services.snapshot()
        return {
            "entities": [snapshot.entities[e].summary() for e in result.focus[:limit]],
            "evidence": [s.public(snippet_chars=700) for s in result.sources if s.kind == "passage"],
        }

    @server.tool(annotations=READ_ONLY)
    async def get_entity(name: str) -> dict[str, Any]:
        """Details and relations of one entity (skill, project, role, organization, degree…)."""
        services = get_services()
        snapshot = services.snapshot()
        entity_id = name if name in snapshot.entities else snapshot.lookup(name)
        if not entity_id:
            return {"error": f"No entity named {name!r}. Try search_graph."}
        entity = snapshot.entities[entity_id]
        relations = [
            {"relation": edge.type, "direction": direction, "entity": snapshot.entities[other].summary(160)}
            for edge, direction, other in snapshot.neighbors(entity_id)
        ]
        evidence = await services.store.entity_evidence(entity_id, limit=4)
        return {"entity": entity.summary(2000), "relations": relations[:60], "evidence": evidence}

    @server.tool(annotations=READ_ONLY)
    async def find_connection(from_entity: str, to_entity: str) -> dict[str, Any]:
        """Shortest path between two entities, e.g. 'GoodBarber' → 'Kubernetes'."""
        snapshot = get_services().snapshot()
        a, b = snapshot.lookup(from_entity), snapshot.lookup(to_entity)
        if not a or not b:
            return {"error": "Unknown entity."}
        ids = snapshot.shortest_path(a, b)
        return {"path": [snapshot.entities[i].summary(160) for i in ids]}

    @server.tool(annotations=READ_ONLY)
    async def assess_job_fit(job_description: str) -> dict[str, Any]:
        """Evidence-backed fit report of Dorian against a job description (score, strengths, gaps)."""
        _guard(cost=3)
        return await get_services().fit.analyze(job_description)

    @server.tool(annotations=READ_ONLY)
    async def get_profile() -> dict[str, Any]:
        """Structured profile: headline, contact links, roles, featured projects and top skills."""
        return _profile(get_services())

    @server.resource("career://profile", name="profile", mime_type="application/json")
    async def profile_resource() -> str:
        return orjson.dumps(_profile(get_services())).decode()

    return server


def _profile(services: Services) -> dict[str, Any]:
    snapshot = services.snapshot()
    people = snapshot.by_type(NodeType.PERSON)
    person = people[0] if people else None
    return {
        "person": person.summary(2000) | person.props if person else None,
        "roles": [e.summary(600) for e in snapshot.by_type(NodeType.ROLE)],
        "projects": [e.summary(400) for e in snapshot.by_type(NodeType.PROJECT)],
        "education": [e.summary(200) for e in snapshot.by_type(NodeType.DEGREE)],
        "skills": sorted(e.name for e in snapshot.by_type(NodeType.SKILL)),
    }


def transport_security(public_url: str, production: bool) -> TransportSecuritySettings:
    """DNS-rebinding protection matters for local servers; the public endpoint sits behind TLS."""
    if production:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*", public_url],
    )
