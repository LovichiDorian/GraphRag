from pathlib import Path

from careergraph.graph.models import KnowledgeGraph
from careergraph.graph.schema import NodeType, RelType
from careergraph.ingest.chunking import chunk_markdown, clean_markdown
from careergraph.ingest.pipeline import apply_implications, build_chunks, compute_skill_evidence
from careergraph.ingest.resolve import add_skill
from careergraph.ingest.sources.profile import build_profile_graph, load_profile
from careergraph.ingest.techmap import canonical, detect_from_manifest, detect_from_paths

DATA = Path(__file__).resolve().parents[3] / "data"


def test_canonical_resolves_aliases_and_versions() -> None:
    assert canonical("k8s").name == "Kubernetes"  # type: ignore[union-attr]
    assert canonical("React 19").name == "React"  # type: ignore[union-attr]
    assert canonical("Postgres").name == "PostgreSQL"  # type: ignore[union-attr]
    assert canonical("NestJS 11").name == "NestJS"  # type: ignore[union-attr]
    assert canonical("React Native").name == "React Native"  # type: ignore[union-attr]
    assert canonical("definitely-not-a-tech") is None


def test_manifest_detection() -> None:
    package_json = '{"dependencies": {"react": "^19", "@nestjs/core": "11", "@prisma/client": "7"}, "devDependencies": {"vite": "7"}}'
    assert {"React", "NestJS", "Prisma", "Vite", "Node.js"} <= detect_from_manifest(
        "frontend/package.json", package_json
    )
    requirements = "langgraph>=0.2\nlangchain-google-genai>=2.0  # Gemini\nfastapi==0.1\n"
    assert {"LangGraph", "Gemini", "FastAPI", "Python"} <= detect_from_manifest(
        "requirements.txt", requirements
    )
    k8s = "apiVersion: batch/v1\nkind: CronJob\nmetadata:\n  annotations:\n    kubernetes.io/ingress.class: traefik\n"
    assert {"Kubernetes", "Cron jobs", "Traefik"} <= detect_from_manifest("k8s/cronjob.yaml", k8s)
    paths = detect_from_paths(["Dockerfile", ".github/workflows/ci.yml", "src/app.kt"])
    assert set(paths) == {"Docker", "GitHub Actions", "Kotlin"}


def test_markdown_chunking_keeps_heading_paths_and_drops_noise() -> None:
    text = (
        "# Title\n\n![badge](https://img.shields.io/x)\n\nIntro paragraph about the project and its goals.\n\n"
        "## Features\n\n" + "A long feature description sentence. " * 60 + "\n\n"
        "## Install\n\n```bash\n"
        + "echo step\n" * 20
        + "```\n\nRun it with a single command and enjoy the result.\n"
    )
    chunks = chunk_markdown(text, doc_title="Doc", max_chars=600)
    assert all(len(c.text) <= 600 for c in chunks)
    assert any(c.title == "Title › Features" for c in chunks)
    assert "img.shields.io" not in clean_markdown(text)
    assert all("echo step" not in c.text for c in chunks)  # long code listings are dropped


def test_profile_graph_from_real_cv() -> None:
    kg = KnowledgeGraph()
    docs = build_profile_graph(load_profile(DATA / "profile.yaml"), kg)
    by_type = {t: [e for e in kg.entities.values() if e.type == t] for t in NodeType}
    assert len(by_type[NodeType.PERSON]) == 1
    assert {r.name for r in by_type[NodeType.ROLE]} >= {"Software Engineer (Apprenticeship) — GoodBarber"}
    assert kg.has_relation("role:goodbarber", RelType.AT, "org:goodbarber")
    assert kg.has_relation(
        "award:innovation-challenge-2025", RelType.AWARDED_FOR, "project:precision-agriculture"
    )
    assert any(d.node.id == "cv:experience:goodbarber" for d in docs)
    # every skill listed on the CV resolves to a canonical node with a domain
    php = kg.entities["skill:php"]
    assert php.props["listed_on_cv"] is True


def test_skill_evidence_weights_professional_use() -> None:
    kg = KnowledgeGraph()
    build_profile_graph(load_profile(DATA / "profile.yaml"), kg)
    sid = add_skill(kg, "LangGraph", source="test")
    assert sid
    kg.add_relation("project:dl-refine", RelType.USES, sid)
    apply_implications(kg)
    compute_skill_evidence(kg, "person:dorian-lovichi")
    assert kg.has_relation("project:dl-refine", RelType.USES, "skill:ai-agents")  # LangGraph ⇒ AI agents
    php = kg.entities["skill:php"].props
    assert php["years"] >= 1.9  # GoodBarber apprenticeship, Sep 2024 – Aug 2026
    assert float(php["strength"]) > float(kg.entities["skill:mongodb"].props["strength"])  # used > listed


def test_chunk_mentions_link_text_to_entities() -> None:
    kg = KnowledgeGraph()
    docs = build_profile_graph(load_profile(DATA / "profile.yaml"), kg)
    build_chunks(kg, docs)
    goodbarber = [c for c in kg.chunks if c.doc_id == "cv:experience:goodbarber"]
    assert goodbarber
    mentions = set().union(*(c.mentions for c in goodbarber))
    assert {"skill:phalcon", "skill:angular", "org:goodbarber"} <= mentions
