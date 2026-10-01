"""CLI: ``python -m careergraph.ingest`` — build the knowledge graph and publish it to Neo4j.

Runs as a Kubernetes Job after every deployment (Argo CD PostSync hook) and as a
nightly CronJob, so new GitHub activity shows up without any manual step.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import orjson

from careergraph.graph.store import Neo4jStore
from careergraph.ingest.cache import KVCache
from careergraph.ingest.pipeline import build_knowledge_graph, graph_version
from careergraph.llm.gemini import Gemini
from careergraph.logs import configure_logging, get_logger
from careergraph.settings import get_settings

log = get_logger("careergraph.ingest")


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    if args.no_llm:
        settings.gemini_api_key = None
    llm = Gemini(settings)
    cache = KVCache(settings.cache_dir / "cache.sqlite3")
    try:
        kg = await build_knowledge_graph(settings, llm, cache)
    finally:
        cache.close()
    version = graph_version(kg)
    log.info(
        "ingest.built", version=version, **{k: v for k, v in kg.meta.items() if isinstance(v, int | float)}
    )

    if args.export:
        payload = kg.model_dump(
            mode="json",
            exclude={
                "entities": {"__all__": {"embedding"}},
                "chunks": {"__all__": {"embedding"}},
                "communities": {"__all__": {"embedding"}},
            },
        )
        await asyncio.to_thread(
            Path(args.export).write_bytes, orjson.dumps(payload, option=orjson.OPT_INDENT_2)
        )
        log.info("ingest.exported", path=args.export)
    if args.dry_run:
        return 0

    store = Neo4jStore(settings)
    try:
        for attempt in range(30):
            if await store.ping():
                break
            log.info("ingest.waiting_for_neo4j", attempt=attempt + 1)
            await asyncio.sleep(5)
        else:
            log.error("ingest.neo4j_unreachable", uri=settings.neo4j_uri)
            return 1
        await store.ensure_schema()
        current = await store.graph_meta()
        if current and current.get("version") == version and not args.force:
            log.info("ingest.unchanged", version=version)
            return 0
        await store.replace_graph(kg, version)
    finally:
        await store.close()
    log.info("ingest.published", version=version)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the career knowledge graph and publish it to Neo4j.")
    parser.add_argument("--dry-run", action="store_true", help="build the graph but do not write to Neo4j")
    parser.add_argument("--force", action="store_true", help="publish even if the content hash is unchanged")
    parser.add_argument(
        "--no-llm", action="store_true", help="skip LLM extraction/embeddings (structure only)"
    )
    parser.add_argument("--export", metavar="PATH", help="write the graph (without embeddings) as JSON")
    sys.exit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
