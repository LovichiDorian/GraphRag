"""Agent events and their encoding as a Vercel AI SDK *UI message stream* (SSE).

The frontend consumes the stream with ``useChat`` from ``@ai-sdk/react``:
agent steps become dynamic tool parts, Gemini thought summaries become
reasoning parts, and the evidence subgraph / sources / follow-ups travel as
typed ``data-*`` parts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, assert_never
from uuid import uuid4

import orjson


@dataclass(slots=True)
class StepStarted:
    id: str
    name: str
    title: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StepFinished:
    id: str
    output: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class ThoughtDelta:
    text: str


@dataclass(slots=True)
class TextDelta:
    text: str


@dataclass(slots=True)
class DataPart:
    name: str
    data: Any
    id: str | None = None
    transient: bool = False


@dataclass(slots=True)
class Metadata:
    data: dict[str, Any]


@dataclass(slots=True)
class Failed:
    message: str


AgentEvent = StepStarted | StepFinished | ThoughtDelta | TextDelta | DataPart | Metadata | Failed

UI_STREAM_HEADERS = {
    "content-type": "text/event-stream",
    "cache-control": "no-cache, no-transform",
    "connection": "keep-alive",
    "x-vercel-ai-ui-message-stream": "v1",
    "x-accel-buffering": "no",
}


def _sse(payload: dict[str, Any]) -> bytes:
    return b"data: " + orjson.dumps(payload) + b"\n\n"


class UIMessageStreamEncoder:
    """Stateful encoder that opens/closes text and reasoning blocks as needed."""

    def __init__(self, message_id: str | None = None) -> None:
        self.message_id = message_id or f"msg_{uuid4().hex[:16]}"
        self._text_id: str | None = None
        self._reasoning_id: str | None = None
        self._tool_names: dict[str, str] = {}
        self._blocks = 0

    def _next_id(self, prefix: str) -> str:
        self._blocks += 1
        return f"{prefix}_{self._blocks}"

    def start(self) -> bytes:
        return _sse({"type": "start", "messageId": self.message_id})

    def _close_reasoning(self) -> list[bytes]:
        if self._reasoning_id is None:
            return []
        out = [_sse({"type": "reasoning-end", "id": self._reasoning_id})]
        self._reasoning_id = None
        return out

    def _close_text(self) -> list[bytes]:
        if self._text_id is None:
            return []
        out = [_sse({"type": "text-end", "id": self._text_id})]
        self._text_id = None
        return out

    def encode(self, event: AgentEvent) -> list[bytes]:
        match event:
            case StepStarted(id=step_id, name=name, title=title, input=step_input):
                self._tool_names[step_id] = name
                return [
                    _sse(
                        {
                            "type": "tool-input-available",
                            "toolCallId": step_id,
                            "toolName": name,
                            "title": title,
                            "input": step_input,
                            "dynamic": True,
                        }
                    )
                ]
            case StepFinished(id=step_id, output=output, error=error):
                if error is not None:
                    return [
                        _sse(
                            {
                                "type": "tool-output-error",
                                "toolCallId": step_id,
                                "errorText": error,
                                "dynamic": True,
                            }
                        )
                    ]
                return [
                    _sse(
                        {
                            "type": "tool-output-available",
                            "toolCallId": step_id,
                            "output": output,
                            "dynamic": True,
                        }
                    )
                ]
            case ThoughtDelta(text=text):
                out = self._close_text()
                if self._reasoning_id is None:
                    self._reasoning_id = self._next_id("reasoning")
                    out.append(_sse({"type": "reasoning-start", "id": self._reasoning_id}))
                out.append(_sse({"type": "reasoning-delta", "id": self._reasoning_id, "delta": text}))
                return out
            case TextDelta(text=text):
                out = self._close_reasoning()
                if self._text_id is None:
                    self._text_id = self._next_id("text")
                    out.append(_sse({"type": "text-start", "id": self._text_id}))
                out.append(_sse({"type": "text-delta", "id": self._text_id, "delta": text}))
                return out
            case DataPart(name=name, data=data, id=part_id, transient=transient):
                payload: dict[str, Any] = {"type": f"data-{name}", "data": data}
                if part_id:
                    payload["id"] = part_id
                if transient:
                    payload["transient"] = True
                return [_sse(payload)]
            case Metadata(data=data):
                return [_sse({"type": "message-metadata", "messageMetadata": data})]
            case Failed(message=message):
                return [
                    *self._close_reasoning(),
                    *self._close_text(),
                    _sse({"type": "error", "errorText": message}),
                ]
        assert_never(event)

    def finish(self, reason: str = "stop") -> list[bytes]:
        return [
            *self._close_reasoning(),
            *self._close_text(),
            _sse({"type": "finish", "finishReason": reason}),
            b"data: [DONE]\n\n",
        ]
