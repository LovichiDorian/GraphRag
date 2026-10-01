"""Streaming endpoints: agentic GraphRAG chat and job-fit analysis."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any, Final, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from careergraph.agent.events import UI_STREAM_HEADERS, AgentEvent, Failed, UIMessageStreamEncoder
from careergraph.agent.orchestrator import ChatTurn
from careergraph.api.deps import enforce_rate_limit, services_of
from careergraph.llm.gemini import LLMBudgetExceededError, LLMUnavailableError
from careergraph.logs import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["agent"])


class MessageIn(BaseModel):
    """Accepts both compact ``{role, content}`` and AI SDK ``{role, parts}`` messages."""

    role: Literal["user", "assistant", "system"]
    content: str | None = Field(default=None, max_length=20_000)
    parts: list[dict[str, Any]] | None = Field(default=None, max_length=200)

    def text(self) -> str:
        if self.content is not None:
            return self.content
        return "".join(str(p.get("text", "")) for p in self.parts or [] if p.get("type") == "text")


class ChatRequest(BaseModel):
    id: str | None = Field(default=None, max_length=128)
    messages: list[MessageIn] = Field(min_length=1, max_length=60)


class FitRequest(BaseModel):
    job_description: str = Field(min_length=80, max_length=40_000, alias="jobDescription")

    model_config = {"populate_by_name": True}


# An SSE comment, ignored by clients: keeps proxies with idle timeouts from cutting the stream
# while a model is slow or the agent waits out a rate-limit cooldown.
HEARTBEAT: Final = b": keep-alive\n\n"
HEARTBEAT_INTERVAL_S: Final = 10.0


class _End:
    """Sentinel for an exhausted event stream."""


async def with_heartbeat(
    events: AsyncIterator[AgentEvent], interval: float = HEARTBEAT_INTERVAL_S
) -> AsyncIterator[AgentEvent | None]:
    """Re-yield ``events``, yielding ``None`` whenever ``interval`` seconds pass without one."""

    async def advance() -> AgentEvent | _End:
        try:
            return await anext(events)
        except StopAsyncIteration:
            return _End()

    pending: asyncio.Task[AgentEvent | _End] | None = None
    try:
        while True:
            pending = pending or asyncio.ensure_future(advance())
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield None
                continue
            item, pending = pending.result(), None
            if isinstance(item, _End):
                return
            yield item
    finally:
        if pending is not None:  # client went away mid-step: stop the agent too
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending


def _stream(events: AsyncIterator[AgentEvent]) -> StreamingResponse:
    async def body() -> AsyncIterator[bytes]:
        encoder = UIMessageStreamEncoder()
        yield encoder.start()
        reason = "stop"
        try:
            async for event in with_heartbeat(events):
                if event is None:
                    yield HEARTBEAT
                    continue
                for chunk in encoder.encode(event):
                    yield chunk
        except LLMBudgetExceededError:
            reason = "error"
            for chunk in encoder.encode(
                Failed("The daily AI budget of this demo is exhausted — please come back tomorrow.")
            ):
                yield chunk
        except LLMUnavailableError as exc:
            reason = "error"
            log.warning("stream.llm_unavailable", error=str(exc)[:300])
            for chunk in encoder.encode(
                Failed("The AI model is temporarily unavailable. Please retry in a minute.")
            ):
                yield chunk
        except Exception:
            reason = "error"
            log.exception("stream.failed")
            for chunk in encoder.encode(Failed("Something went wrong while answering. Please retry.")):
                yield chunk
        for chunk in encoder.finish(reason):
            yield chunk

    return StreamingResponse(body(), headers=UI_STREAM_HEADERS)


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request) -> StreamingResponse:
    services = services_of(request)
    enforce_rate_limit(request)
    messages = [m for m in payload.messages if m.role != "system"]
    if not messages or messages[-1].role != "user":
        raise HTTPException(422, "The last message must come from the user.")
    question = messages[-1].text().strip()
    if not question:
        raise HTTPException(422, "Empty question.")
    if len(question) > services.settings.max_question_chars:
        raise HTTPException(
            413, f"Questions are limited to {services.settings.max_question_chars} characters."
        )
    history = [
        ChatTurn(role=m.role, text=m.text()[:2000])  # type: ignore[arg-type]
        for m in messages[:-1][-services.settings.max_history_messages :]
        if m.text().strip()
    ]
    return _stream(services.agent.run(question, history))


@router.post("/fit")
async def fit(payload: FitRequest, request: Request) -> StreamingResponse:
    services = services_of(request)
    enforce_rate_limit(request, cost=3)
    if not services.llm.enabled:
        raise HTTPException(503, "The AI model is not configured on this server.")
    return _stream(services.fit.run(payload.job_description))
