"""Gemini client: ordered model fallback chains, quota-aware circuit breakers, daily budget.

Free-tier keys have small per-model quotas (e.g. 5 requests/minute/model) and
preview models regularly answer 503 "high demand". Every call therefore walks
an ordered chain of models and skips the ones whose breaker is open. A 429
opens the breaker for exactly the ``retryDelay`` Google returns (or until the
next day for daily quotas). Interactive calls fail over instantly; batch
calls (ingestion) can be *patient* and wait for the earliest model to recover.
Streaming calls fall back until the first token has reached the client.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
import numpy as np
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from careergraph.logs import get_logger
from careergraph.settings import Settings

log = get_logger(__name__)

Thinking = Literal["minimal", "low", "medium", "high"]
EmbedTask = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY", "SEMANTIC_SIMILARITY", "CLUSTERING"]

_TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504}
_EMBED_BATCH = 50
_ERRORS = (genai_errors.APIError, httpx.TransportError, TimeoutError)


class LLMUnavailableError(RuntimeError):
    """No model of the fallback chain could serve the request."""


class LLMBudgetExceededError(LLMUnavailableError):
    """The daily request budget that protects the API key is exhausted."""


class LLMStreamInterruptedError(LLMUnavailableError):
    """The model failed after tokens were already streamed to the client."""


@dataclass(slots=True)
class StreamDelta:
    kind: Literal["model", "text", "thought"]
    text: str


@dataclass(slots=True)
class _Breaker:
    failures: int = 0
    open_until: float = 0.0


@dataclass
class LLMStats:
    requests: Counter[str] = field(default_factory=Counter)
    failures: Counter[str] = field(default_factory=Counter)
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0


class DailyBudget:
    """Hard cap on LLM requests per UTC day (per process)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0
        self._day = datetime.now(UTC).date()

    def consume(self, n: int = 1) -> None:
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day, self.used = today, 0
        if self.used + n > self.limit:
            raise LLMBudgetExceededError("Daily LLM budget exhausted — try again tomorrow.")
        self.used += n

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


def _status_of(exc: BaseException) -> int | None:
    if isinstance(exc, genai_errors.APIError):
        return int(exc.code) if exc.code is not None else None
    return None


def _is_transient(exc: BaseException) -> bool:
    status = _status_of(exc)
    if status is not None:
        return status in _TRANSIENT_STATUS
    return isinstance(exc, httpx.TransportError | TimeoutError)


def quota_info(exc: BaseException) -> tuple[float | None, bool]:
    """(retry_after_seconds, is_daily_quota) parsed from a Google 429 error payload."""
    details: Any = getattr(exc, "details", None)
    error = details.get("error", details) if isinstance(details, dict) else {}
    retry: float | None = None
    daily = False
    for item in (error.get("details") or []) if isinstance(error, dict) else []:
        if not isinstance(item, dict):
            continue
        if delay := item.get("retryDelay"):
            try:
                retry = float(str(delay).rstrip("s"))
            except ValueError:
                retry = None
        for violation in item.get("violations") or []:
            if "PerDay" in str(violation.get("quotaId", "")):
                daily = True
    return retry, daily


def _normalize(vector: Sequence[float]) -> list[float]:
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return (arr / norm).tolist() if norm > 0 else arr.tolist()


class Gemini:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stats = LLMStats()
        self.budget = DailyBudget(settings.llm_daily_budget)
        self._breakers: dict[str, _Breaker] = {}
        self._client: genai.Client | None = None
        if settings.llm_enabled and settings.gemini_api_key is not None:
            self._client = genai.Client(
                api_key=settings.gemini_api_key.get_secret_value(),
                vertexai=settings.google_genai_use_vertexai or None,
                http_options=types.HttpOptions(timeout=int(settings.llm_timeout_s * 1000)),
            )

    # ── plumbing ──────────────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self._client is not None

    def _require_client(self) -> genai.Client:
        if self._client is None:
            raise LLMUnavailableError("GEMINI_API_KEY is not configured.")
        return self._client

    def _open_until(self, model: str) -> float:
        breaker = self._breakers.get(model)
        return breaker.open_until if breaker else 0.0

    def _chain(self, models: Sequence[str], *, probe: bool) -> list[str]:
        """Healthy models in preference order; with ``probe``, fall back to the soonest-recovering one."""
        now = time.monotonic()
        healthy = [m for m in models if self._open_until(m) <= now]
        if healthy or not probe:
            return healthy
        return sorted(models, key=self._open_until)[:1]

    def _seconds_to_recovery(self, models: Sequence[str]) -> float:
        return max(0.0, min(self._open_until(m) for m in models) - time.monotonic()) if models else 0.0

    def _record_failure(self, model: str, exc: BaseException) -> None:
        breaker = self._breakers.setdefault(model, _Breaker())
        breaker.failures += 1
        status = _status_of(exc)
        retry_after, daily = quota_info(exc) if status == 429 else (None, False)
        if status == 404:  # model retired or not available for this key
            cooldown = 6 * 3600.0
        elif daily:
            cooldown = 3600.0
        elif retry_after is not None:
            cooldown = retry_after + 1.0
        else:
            cooldown = min(self.settings.circuit_open_s * 2 ** (breaker.failures - 1), 900.0)
        breaker.open_until = time.monotonic() + cooldown
        self.stats.failures[model] += 1
        log.warning(
            "llm.model_failed",
            model=model,
            status=status,
            cooldown_s=round(cooldown, 1),
            error=str(exc)[:160],
        )

    def _record_success(self, model: str, usage: types.GenerateContentResponseUsageMetadata | None) -> None:
        self._breakers.pop(model, None)
        self.stats.requests[model] += 1
        if usage is not None:
            self.stats.input_tokens += usage.prompt_token_count or 0
            self.stats.output_tokens += usage.candidates_token_count or 0
            self.stats.thought_tokens += usage.thoughts_token_count or 0

    @staticmethod
    def _thinking(model: str, level: Thinking | None, include_thoughts: bool) -> types.ThinkingConfig | None:
        if level is None or model.startswith("gemma"):
            return None
        if model.startswith("gemini-2"):
            budget = {"minimal": 0, "low": 512, "medium": 2048, "high": 8192}[level]
            return types.ThinkingConfig(thinking_budget=budget, include_thoughts=include_thoughts)
        return types.ThinkingConfig(thinking_level=level, include_thoughts=include_thoughts)

    def _config(
        self,
        model: str,
        *,
        system: str | None,
        temperature: float,
        thinking: Thinking | None,
        include_thoughts: bool = False,
        json_schema: type[BaseModel] | None = None,
        max_output_tokens: int | None = None,
    ) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_config=self._thinking(model, thinking, include_thoughts),
            response_mime_type="application/json" if json_schema else None,
            response_json_schema=json_schema.model_json_schema() if json_schema else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    async def _wait_for_capacity(self, models: Sequence[str], deadline: float) -> bool:
        """Patient mode: sleep until the earliest model recovers, if that fits before ``deadline``."""
        wait = self._seconds_to_recovery(models)
        if time.monotonic() + wait > deadline:
            return False
        log.info("llm.waiting_for_quota", seconds=round(wait, 1))
        await asyncio.sleep(max(wait, 0.5))
        return True

    # ── public API ────────────────────────────────────────────────────────────
    async def generate_json[T: BaseModel](
        self,
        *,
        models: Sequence[str],
        prompt: str | list[types.Content],
        schema: type[T],
        system: str | None = None,
        temperature: float = 0.2,
        thinking: Thinking | None = "low",
        max_output_tokens: int | None = None,
        patience_s: float = 0.0,
    ) -> tuple[T, str]:
        """Structured output validated against a Pydantic model. Returns (object, model_used)."""
        client = self._require_client()
        deadline = time.monotonic() + patience_s
        last_error: BaseException | None = None
        while True:
            for model in self._chain(models, probe=patience_s <= 0):
                self.budget.consume()
                try:
                    response = await client.aio.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=self._config(
                            model,
                            system=system,
                            temperature=temperature,
                            thinking=thinking,
                            json_schema=schema,
                            max_output_tokens=max_output_tokens,
                        ),
                    )
                    parsed = schema.model_validate_json(response.text or "")
                except ValidationError as exc:  # malformed JSON: another model may do better
                    last_error = exc
                    self.stats.failures[model] += 1
                    log.warning("llm.invalid_json", model=model, error=str(exc)[:200])
                    continue
                except _ERRORS as exc:
                    last_error = exc
                    if _status_of(exc) in {401, 403}:
                        raise LLMUnavailableError("Gemini rejected the API key.") from exc
                    self._record_failure(model, exc)
                    continue
                self._record_success(model, response.usage_metadata)
                return parsed, model
            if patience_s <= 0 or not await self._wait_for_capacity(models, deadline):
                raise LLMUnavailableError(f"All models failed: {last_error}") from last_error

    async def stream_text(
        self,
        *,
        models: Sequence[str],
        contents: str | list[types.Content],
        system: str | None = None,
        temperature: float = 0.4,
        thinking: Thinking | None = "low",
        include_thoughts: bool = False,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[StreamDelta]:
        """Yield a ``model`` delta, then ``thought``/``text`` deltas as they arrive."""
        client = self._require_client()
        last_error: BaseException | None = None
        for model in self._chain(models, probe=True):
            self.budget.consume()
            started = False
            usage: types.GenerateContentResponseUsageMetadata | None = None
            try:
                stream = await client.aio.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=self._config(
                        model,
                        system=system,
                        temperature=temperature,
                        thinking=thinking,
                        include_thoughts=include_thoughts,
                        max_output_tokens=max_output_tokens,
                    ),
                )
                async for chunk in stream:
                    usage = chunk.usage_metadata or usage
                    candidate = chunk.candidates[0] if chunk.candidates else None
                    parts = candidate.content.parts if candidate and candidate.content else None
                    for part in parts or []:
                        if not part.text:
                            continue
                        if not started:
                            started = True
                            yield StreamDelta("model", model)
                        yield StreamDelta("thought" if part.thought else "text", part.text)
            except _ERRORS as exc:
                last_error = exc
                if started:
                    self._record_failure(model, exc)
                    raise LLMStreamInterruptedError(str(exc)) from exc
                if _status_of(exc) in {401, 403}:
                    raise LLMUnavailableError("Gemini rejected the API key.") from exc
                self._record_failure(model, exc)
                continue
            if not started:
                yield StreamDelta("model", model)
            self._record_success(model, usage)
            return
        raise LLMUnavailableError(f"All models failed: {last_error}") from last_error

    async def generate_text(self, **kwargs: Any) -> tuple[str, str]:
        """Non-streaming convenience wrapper around :meth:`stream_text`."""
        model, parts = "", []
        async for delta in self.stream_text(**kwargs):
            if delta.kind == "model":
                model = delta.text
            elif delta.kind == "text":
                parts.append(delta.text)
        return "".join(parts), model

    async def embed(
        self, texts: Sequence[str], task: EmbedTask, *, patience_s: float = 8.0
    ) -> list[list[float]]:
        """Batch-embed texts (one Content per text), L2-normalised, quota-aware retries."""
        client = self._require_client()
        model = self.settings.embedding_model
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH):
            batch = texts[start : start + _EMBED_BATCH]
            deadline = time.monotonic() + patience_s
            attempt = 0
            while True:
                self.budget.consume()
                try:
                    response = await client.aio.models.embed_content(
                        model=model,
                        contents=[types.Content(parts=[types.Part(text=text[:20000])]) for text in batch],
                        config=types.EmbedContentConfig(
                            output_dimensionality=self.settings.embedding_dim, task_type=task
                        ),
                    )
                    break
                except _ERRORS as exc:
                    attempt += 1
                    retry_after, daily = quota_info(exc)
                    wait = retry_after + 0.5 if retry_after is not None else 1.5 * 2**attempt
                    if not _is_transient(exc) or daily or time.monotonic() + wait > deadline:
                        self.stats.failures[model] += 1
                        raise LLMUnavailableError(f"Embedding failed: {exc}") from exc
                    log.info("llm.embed_retry", seconds=round(wait, 1), attempt=attempt)
                    await asyncio.sleep(wait)
            embeddings = response.embeddings or []
            if len(embeddings) != len(batch):
                raise LLMUnavailableError(f"Expected {len(batch)} embeddings, got {len(embeddings)}")
            vectors.extend(_normalize(e.values or []) for e in embeddings)
            self.stats.requests[model] += 1
        return vectors

    async def embed_one(self, text: str, task: EmbedTask = "RETRIEVAL_QUERY") -> list[float]:
        return (await self.embed([text], task))[0]

    def health(self) -> dict[str, object]:
        now = time.monotonic()
        return {
            "enabled": self.enabled,
            "budget_remaining": self.budget.remaining,
            "open_circuits": {
                model: round(b.open_until - now) for model, b in self._breakers.items() if b.open_until > now
            },
        }
