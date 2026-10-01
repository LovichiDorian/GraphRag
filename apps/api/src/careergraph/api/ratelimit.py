"""In-process sliding-window rate limiter (per client, per minute and per UTC day).

Traefik applies a first, coarse rate limit at the edge; this second layer
protects the Gemini key from abuse of the expensive endpoints.
"""

from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime

from starlette.requests import Request


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int, max_clients: int = 50_000) -> None:
        self.per_minute = per_minute
        self.per_day = per_day
        self.max_clients = max_clients
        self._minute: dict[str, deque[float]] = {}
        self._day: dict[str, tuple[str, int]] = {}

    def hit(self, key: str, cost: int = 1) -> float | None:
        """Record ``cost`` hits; return ``retry_after`` seconds when the client is over its limit."""
        now = time.monotonic()
        today = datetime.now(UTC).date().isoformat()
        window = self._minute.setdefault(key, deque())
        while window and now - window[0] > 60:
            window.popleft()
        day, count = self._day.get(key, (today, 0))
        if day != today:
            count = 0
        if count + cost > self.per_day:
            return self._seconds_to_midnight()
        if len(window) + cost > self.per_minute:
            return max(1.0, 60 - (now - window[0])) if window else 60.0
        window.extend([now] * cost)
        self._day[key] = (today, count + cost)
        if len(self._minute) > self.max_clients:
            self._evict(now)
        return None

    def _evict(self, now: float) -> None:
        stale = [k for k, w in self._minute.items() if not w or now - w[-1] > 60]
        for key in stale:
            self._minute.pop(key, None)

    @staticmethod
    def _seconds_to_midnight() -> float:
        now = datetime.now(UTC)
        return float(86400 - (now.hour * 3600 + now.minute * 60 + now.second))


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if real_ip := request.headers.get("x-real-ip"):
        return real_ip.strip()
    return request.client.host if request.client else "unknown"
