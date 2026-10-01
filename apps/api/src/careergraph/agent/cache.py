"""Answer cache: in-memory LRU backed by Neo4j, keyed by question and profile revision.

Recruiters mostly click the starter questions, and free-tier Gemini keys allow
~20 requests/day/model, so fully rendered answers (the whole event stream) are
cached and replayed. Entries survive restarts (persisted as :CachedAnswer
nodes) and are invalidated when the curated profile changes or after the TTL.
"""

from __future__ import annotations

import dataclasses
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

import orjson

from careergraph.agent.events import (
    AgentEvent,
    DataPart,
    Failed,
    Metadata,
    StepFinished,
    StepStarted,
    TextDelta,
    ThoughtDelta,
)
from careergraph.logs import get_logger

if TYPE_CHECKING:
    from careergraph.graph.store import Neo4jStore

log = get_logger(__name__)

_EVENT_TYPES: dict[str, type[Any]] = {
    cls.__name__: cls
    for cls in (StepStarted, StepFinished, ThoughtDelta, TextDelta, DataPart, Metadata, Failed)
}


def dump_events(events: list[AgentEvent]) -> str:
    return orjson.dumps([{"t": type(e).__name__, **dataclasses.asdict(e)} for e in events]).decode()


def load_events(payload: str) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    for item in orjson.loads(payload):
        cls = _EVENT_TYPES[item.pop("t")]
        events.append(cls(**item))
    return events


class AnswerCache:
    def __init__(self, ttl_s: float, store: Neo4jStore | None = None, max_items: int = 256) -> None:
        self.ttl_s = ttl_s
        self.store = store
        self.max_items = max_items
        self._items: OrderedDict[str, tuple[float, str, list[AgentEvent]]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def _fresh(self, created: float, revision: str, wanted: str) -> bool:
        return revision == wanted and time.time() - created <= self.ttl_s

    async def get(self, key: str, revision: str) -> list[AgentEvent] | None:
        item = self._items.get(key)
        if item is not None and self._fresh(item[0], item[1], revision):
            self._items.move_to_end(key)
            self.hits += 1
            return item[2]
        if self.store is not None:
            try:
                row = await self.store.get_cached_answer(key)
            except Exception as exc:  # noqa: BLE001 - cache must never break answering
                log.warning("cache.read_failed", error=str(exc)[:200])
                row = None
            if row and self._fresh(float(row["created"]), str(row["revision"]), revision):
                events = load_events(row["events"])
                self._remember(key, float(row["created"]), revision, events)
                self.hits += 1
                return events
        self.misses += 1
        return None

    async def contains(self, key: str, revision: str) -> bool:
        hits, misses = self.hits, self.misses
        found = await self.get(key, revision) is not None
        self.hits, self.misses = hits, misses
        return found

    async def put(self, key: str, revision: str, events: list[AgentEvent]) -> None:
        created = time.time()
        self._remember(key, created, revision, events)
        if self.store is not None:
            try:
                await self.store.save_cached_answer(key, revision, dump_events(events), created)
            except Exception as exc:  # noqa: BLE001
                log.warning("cache.write_failed", error=str(exc)[:200])

    def _remember(self, key: str, created: float, revision: str, events: list[AgentEvent]) -> None:
        self._items[key] = (created, revision, events)
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()
