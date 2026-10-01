"""FastAPI application factory."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from careergraph.api.metrics import REGISTRY, ServicesCollector, metrics_middleware
from careergraph.api.ratelimit import RateLimiter
from careergraph.api.routes import chat, graph, meta
from careergraph.logs import configure_logging, get_logger
from careergraph.mcp_server import build_mcp_server, transport_security
from careergraph.services import Services
from careergraph.settings import Settings, get_settings

log = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    services = Services(settings)
    mcp = build_mcp_server(lambda: services)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=transport_security(settings.public_url, settings.environment == "production"),
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        collector = ServicesCollector(services)
        REGISTRY.register(collector)
        await services.start()
        log.info(
            "api.started",
            environment=settings.environment,
            llm=services.llm.enabled,
            graph_version=services.snapshot().version,
        )
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            REGISTRY.unregister(collector)
            await services.stop()

    app = FastAPI(
        title="Dorian Lovichi — Career GraphRAG API",
        version="1.0.0",
        description="Agentic GraphRAG over a CV and GitHub repositories (Gemini · Neo4j · MCP).",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.services = services
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_per_day)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type", "mcp-protocol-version", "mcp-session-id", "authorization"],
        max_age=600,
    )
    app.middleware("http")(metrics_middleware)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    app.include_router(meta.router)
    app.include_router(graph.router)
    app.include_router(chat.router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("api.unhandled_error", error=str(exc)[:300], exc_info=exc)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    # MCP Streamable HTTP endpoint (stateless, JSON responses) at /mcp.
    for route in mcp_app.routes:
        app.router.routes.append(route)
    return app
