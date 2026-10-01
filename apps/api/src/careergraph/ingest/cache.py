"""Content-addressed cache (SQLite) for LLM extractions and embeddings.

Keys are SHA-256 hashes of (model, prompt version, input text): re-running the
nightly ingestion only pays for content that actually changed.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import orjson


def content_key(*parts: object) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode())
        digest.update(b"\x1f")
    return digest.hexdigest()


class KVCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS kv (ns TEXT NOT NULL, key TEXT NOT NULL, value BLOB NOT NULL, "
            "created REAL NOT NULL, PRIMARY KEY (ns, key))"
        )
        self.hits = 0
        self.misses = 0

    def close(self) -> None:
        self._db.close()

    def get_json(self, ns: str, key: str) -> Any | None:
        row = self._db.execute("SELECT value FROM kv WHERE ns = ? AND key = ?", (ns, key)).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        return orjson.loads(row[0])

    def put_json(self, ns: str, key: str, value: Any) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO kv (ns, key, value, created) VALUES (?, ?, ?, ?)",
            (ns, key, orjson.dumps(value), time.time()),
        )
        self._db.commit()

    def get_vectors(self, keys: Sequence[str]) -> dict[str, list[float]]:
        found: dict[str, list[float]] = {}
        for start in range(0, len(keys), 500):
            batch = list(keys[start : start + 500])
            marks = ",".join("?" * len(batch))
            rows = self._db.execute(f"SELECT key, value FROM kv WHERE ns = 'vec' AND key IN ({marks})", batch)
            for key, value in rows:
                found[key] = np.frombuffer(value, dtype=np.float32).tolist()
        self.hits += len(found)
        self.misses += len(keys) - len(found)
        return found

    def put_vectors(self, items: Iterable[tuple[str, Sequence[float]]]) -> None:
        now = time.time()
        self._db.executemany(
            "INSERT OR REPLACE INTO kv (ns, key, value, created) VALUES ('vec', ?, ?, ?)",
            [(key, np.asarray(vector, dtype=np.float32).tobytes(), now) for key, vector in items],
        )
        self._db.commit()
