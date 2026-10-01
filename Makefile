.DEFAULT_GOAL := help
API := apps/api
WEB := apps/web

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

up: ## Full stack in Docker (Neo4j, API, ingestion, web) on http://localhost:3000
	docker compose up --build

neo4j: ## Only Neo4j, for local development
	docker compose up -d neo4j

install: ## Install API and web dependencies
	cd $(API) && uv sync
	cd $(WEB) && pnpm install

ingest: ## Build the knowledge graph into the local Neo4j
	cd $(API) && DATA_DIR=../../data uv run careergraph-ingest

api: ## Run the API with reload-free uvicorn on :8000
	cd $(API) && DATA_DIR=../../data uv run careergraph-api

web: ## Run Next.js dev server on :3000 (proxies /api to :8000)
	cd $(WEB) && pnpm dev

check: ## Lint, type-check and test everything (same as CI)
	cd $(API) && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
	cd $(WEB) && pnpm lint && pnpm typecheck

k8s: ## Render and validate the Kubernetes manifests
	kustomize build deploy/k8s/overlays/prod | kubeconform -strict -summary -schema-location default \
	  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

.PHONY: help up neo4j install ingest api web check k8s
