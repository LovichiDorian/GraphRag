# syntax=docker/dockerfile:1.10
# Build context: repository root (the image embeds data/ — the curated knowledge base).

FROM ghcr.io/astral-sh/uv:0.12.21 AS uv

FROM python:3.14.7-slim AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
# Dependencies first (cached layer), then the project itself.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=apps/api/uv.lock,target=uv.lock \
    --mount=type=bind,source=apps/api/pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY apps/api/ ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

FROM python:3.14.7-slim AS runtime
LABEL org.opencontainers.image.title="careergraph-api" \
      org.opencontainers.image.description="Agentic GraphRAG API + ingestion (FastAPI, Gemini, Neo4j, MCP)" \
      org.opencontainers.image.source="https://github.com/LovichiDorian/GraphRag" \
      org.opencontainers.image.licenses="MIT"
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app \
    && mkdir -p /cache && chown 10001:10001 /cache
COPY --from=build /opt/venv /opt/venv
COPY data /app/data
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data \
    CACHE_DIR=/cache \
    ENVIRONMENT=production \
    LOG_JSON=true \
    HOST=0.0.0.0 \
    PORT=8000
WORKDIR /app
USER 10001:10001
EXPOSE 8000
CMD ["careergraph-api"]
