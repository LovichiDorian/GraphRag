# How this site works (Agentic GraphRAG — Career Knowledge Graph)

This website, graphrag.dorianlovichi.com, was designed and built by Dorian Lovichi as an
open-source showcase of applied AI engineering and DevOps. Its source code is public at
github.com/LovichiDorian/GraphRag.

## Knowledge graph construction

An ingestion job reads Dorian's résumé (stored as structured YAML), these notes and his public
GitHub repositories. For every repository it downloads the source archive and analyses dependency
manifests (package.json, requirements.txt, pyproject.toml, Gradle, pubspec.yaml), Dockerfiles,
Kubernetes manifests and CI workflows, so skills are verified against real code. Gemini models
perform schema-guided extraction with structured JSON output validated by Pydantic. Entity
resolution maps aliases to a canonical ontology of technologies, and unknown names are merged by
embedding similarity. Louvain community detection groups the graph into themes, each summarised
by an LLM-written report. Entities, evidence chunks and community reports are embedded with
gemini-embedding-2 (768 dimensions) and stored in Neo4j with vector and full-text indexes.
LLM outputs and embeddings are cached by content hash, so the nightly re-ingestion only pays for
what changed.

## Answering questions

Each question goes through three agents. A planner agent rewrites the question, decomposes it
into search queries, links entity names and can write a guarded, read-only Cypher query for
counting or listing questions. A retriever runs hybrid search (vector similarity plus Lucene
full-text, fused with Reciprocal Rank Fusion) and expands the results with Personalized PageRank
over the knowledge graph, in the style of HippoRAG, to collect multi-hop evidence. A synthesizer
agent streams a grounded answer with numbered citations. The stream follows the Vercel AI SDK
UI message protocol, and the evidence subgraph is highlighted live in a 3D graph built with
three.js. Models are called through ordered fallback chains with circuit breakers and quota-aware
retries, and answers to frequent questions are cached in Neo4j.

The site also offers a job-fit analyzer: requirements are extracted from a pasted job
description, evidence is retrieved for each requirement, and an LLM grades them as strong,
partial, transferable or gap; the overall score is computed deterministically from those grades.
A public Model Context Protocol (MCP) server at /mcp exposes the same capabilities as tools for
AI assistants.

## Stack and deployment

Backend: Python 3.14, FastAPI, Pydantic, the async Neo4j driver, the Google Gen AI SDK, uv,
Prometheus metrics and structured JSON logs. Frontend: Next.js 16, React 19, TypeScript,
Tailwind CSS 4, the Vercel AI SDK, react-force-graph with three.js and bloom post-processing.

The application runs on a k3s Kubernetes cluster: Neo4j as a StatefulSet with a persistent
volume, the API and the web front end as hardened Deployments (non-root, read-only root
filesystem, dropped capabilities), Traefik ingress with rate limiting and security headers,
cert-manager for Let's Encrypt TLS, NetworkPolicies isolating the database, and a nightly
CronJob that rebuilds the graph. Deployment is GitOps with Argo CD. GitHub Actions run linting,
type checks and tests, build multi-architecture images (amd64 and arm64) on native runners,
attach SBOM and provenance attestations, sign them with cosign and scan them with Trivy, then
commit the new image tags that Argo CD rolls out.
