"""Request-scoped helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fastapi import HTTPException, Request

from careergraph.api.metrics import RATE_LIMITED
from careergraph.api.ratelimit import RateLimiter, client_key

if TYPE_CHECKING:
    from careergraph.services import Services


def services_of(request: Request) -> Services:
    return cast("Services", request.app.state.services)


def enforce_rate_limit(request: Request, cost: int = 1) -> None:
    limiter = cast(RateLimiter, request.app.state.limiter)
    retry_after = limiter.hit(client_key(request), cost)
    if retry_after is not None:
        RATE_LIMITED.inc()
        raise HTTPException(
            status_code=429,
            detail="Too many questions for now — please wait a moment.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
