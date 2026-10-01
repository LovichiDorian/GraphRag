"""Service container shared by the HTTP API and the MCP server."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from careergraph.agent.orchestrator import CareerAgent
from careergraph.agent.prompts import PROMPT_VERSION, STARTER_QUESTIONS
from careergraph.fit.analyzer import FitAnalyzer
from careergraph.graph.snapshot import GraphSnapshot, normalize_name
from careergraph.graph.store import Neo4jStore
from careergraph.llm.gemini import Gemini
from careergraph.logs import get_logger
from careergraph.retrieval.hybrid import HybridRetriever
from careergraph.settings import Settings

log = get_logger(__name__)


class Services:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm = Gemini(settings)
        self.store = Neo4jStore(settings)
        self._snapshot = GraphSnapshot("empty", [], [])
        self.meta: dict[str, Any] | None = None
        self.retriever = HybridRetriever(self.store, self.llm, self.snapshot)
        self.agent = CareerAgent(
            settings, self.llm, self.store, self.retriever, self.snapshot, revision=self.revision
        )
        self.fit = FitAnalyzer(settings, self.llm, self.retriever, self.snapshot)
        self.neo4j_ready = False
        self._refresh_task: asyncio.Task[None] | None = None
        self._warm_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def snapshot(self) -> GraphSnapshot:
        return self._snapshot

    def revision(self) -> str:
        """Cache revision: changes with the curated profile (profile.yaml, notes) or the prompts."""
        stats = (self.meta or {}).get("stats") or {}
        return f"{stats.get('profile_revision') or self._snapshot.version}:{PROMPT_VERSION}"

    async def start(self) -> None:
        # Never block startup on Neo4j: /healthz must answer while the database boots
        # (the readiness probe keeps traffic away until the graph is loaded).
        await self._connect()
        self._refresh_task = asyncio.create_task(self._refresh_loop(), name="graph-refresh")

    async def stop(self) -> None:
        for task in (self._refresh_task, self._warm_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await self.store.close()

    async def _connect(self) -> None:
        if not await self.store.ping():
            log.warning("startup.neo4j_not_ready", uri=self.settings.neo4j_uri)
            return
        try:
            await self.store.ensure_schema()
            await self.refresh(force=True)
            self.neo4j_ready = True
        except Exception as exc:  # noqa: BLE001 - keep serving, the refresh loop retries
            log.warning("startup.graph_load_failed", error=str(exc)[:300])

    async def refresh(self, *, force: bool = False) -> bool:
        """Reload the in-memory snapshot when the ingestion job published a new version."""
        async with self._lock:
            meta = await self.store.graph_meta()
            version = str(meta["version"]) if meta else "empty"
            if not force and version == self._snapshot.version:
                return False
            rows = await self.store.load_graph_rows()
            snapshot = GraphSnapshot.from_rows(version, rows)
            self._snapshot, self.meta = snapshot, meta
            self.agent.cache.clear()
            self._schedule_warmup()
            log.info(
                "graph.snapshot_loaded",
                version=version,
                entities=len(snapshot.entities),
                edges=len(snapshot.edges),
            )
            return True

    def _schedule_warmup(self) -> None:
        if not (self.settings.warm_cache and self.llm.enabled and self._snapshot.entities):
            return
        if self._warm_task and not self._warm_task.done():
            self._warm_task.cancel()
        self._warm_task = asyncio.create_task(self._warmup(), name="answer-warmup")

    async def _warmup(self) -> None:
        """Pre-compute answers to the starter questions (paced, skipped when already cached)."""
        await asyncio.sleep(5)
        revision = self.revision()
        for question in STARTER_QUESTIONS:
            if await self.agent.cache.contains(normalize_name(question), revision):
                continue
            try:
                async for _ in self.agent.run(question, []):
                    pass
                log.info("warmup.cached", question=question)
            except Exception as exc:  # noqa: BLE001 - warmup is best effort
                log.warning("warmup.failed", question=question, error=str(exc)[:200])
                return
            await asyncio.sleep(20)

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.graph_refresh_s if self.neo4j_ready else 10)
            try:
                if not self.neo4j_ready:
                    await self._connect()
                    continue
                await self.refresh()
            except Exception as exc:  # noqa: BLE001 - background loop must survive
                self.neo4j_ready = False
                log.warning("graph.refresh_failed", error=str(exc)[:300])
