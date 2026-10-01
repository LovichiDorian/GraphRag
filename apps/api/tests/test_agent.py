from typing import ClassVar

import orjson

from careergraph.agent.cache import dump_events, load_events
from careergraph.agent.events import (
    DataPart,
    Failed,
    Metadata,
    StepFinished,
    StepStarted,
    TextDelta,
    ThoughtDelta,
    UIMessageStreamEncoder,
)
from careergraph.api.ratelimit import RateLimiter
from careergraph.fit.analyzer import FitReport, JobSpec, Requirement, RequirementAssessment, compute_score
from careergraph.llm.gemini import quota_info


def _decode(chunks: list[bytes]) -> list[dict[str, object]]:
    out = []
    for chunk in chunks:
        assert chunk.startswith(b"data: ")
        assert chunk.endswith(b"\n\n")
        body = chunk[6:-2]
        if body != b"[DONE]":
            out.append(orjson.loads(body))
    return out


def test_ui_message_stream_protocol() -> None:
    encoder = UIMessageStreamEncoder("msg_1")
    chunks = [encoder.start()]
    for event in (
        StepStarted("plan", "planner", "Planning", {"q": "x"}),
        StepFinished("plan", {"intent": "skills"}),
        ThoughtDelta("thinking…"),
        TextDelta("Hello "),
        TextDelta("world [1]"),
        DataPart("graph", {"nodes": ["a"]}, id="graph"),
        Metadata({"model": "m"}),
    ):
        chunks += encoder.encode(event)
    chunks += encoder.finish()
    events = _decode(chunks)
    types = [e["type"] for e in events]
    assert types == [
        "start",
        "tool-input-available",
        "tool-output-available",
        "reasoning-start",
        "reasoning-delta",
        "reasoning-end",
        "text-start",
        "text-delta",
        "text-delta",
        "data-graph",
        "message-metadata",
        "text-end",
        "finish",
    ]
    assert events[1]["dynamic"] is True
    assert events[1]["toolName"] == "planner"
    assert chunks[-1] == b"data: [DONE]\n\n"
    assert events[7]["id"] == events[6]["id"]


def test_failed_event_closes_open_blocks() -> None:
    encoder = UIMessageStreamEncoder()
    encoder.encode(TextDelta("partial"))
    events = _decode(encoder.encode(Failed("boom")))
    assert [e["type"] for e in events] == ["text-end", "error"]


def test_cached_events_roundtrip() -> None:
    events = [
        StepStarted("plan", "planner", "P", {"a": 1}),
        TextDelta("hi"),
        DataPart("graph", {"n": [1]}, id="g"),
    ]
    assert load_events(dump_events(events)) == events


def test_rate_limiter_minute_and_cost() -> None:
    limiter = RateLimiter(per_minute=3, per_day=10)
    assert limiter.hit("ip") is None
    assert limiter.hit("ip", cost=2) is None
    assert limiter.hit("ip") is not None
    assert limiter.hit("other") is None


def test_fit_score_is_deterministic() -> None:
    spec = JobSpec(
        title="AI Engineer",
        language="en",
        requirements=[
            Requirement(requirement="Python", category="technical", importance="must", search_query="python"),
            Requirement(requirement="AWS", category="technical", importance="nice", search_query="aws"),
            Requirement(
                requirement="US work permit", category="logistics", importance="must", search_query="visa"
            ),
        ],
    )
    report = FitReport(
        headline="",
        summary="",
        strengths=[],
        gaps=[],
        interview_questions=[],
        assessments=[
            RequirementAssessment(index=0, status="strong", rationale="", evidence=[1]),
            RequirementAssessment(index=1, status="transferable", rationale="", evidence=[]),
            RequirementAssessment(index=2, status="gap", rationale="", evidence=[]),
        ],
    )
    score = compute_score(spec, report)
    assert score["percent"] == round(100 * (2 * 1.0 + 1 * 0.35) / 5)
    assert score["mustHaveGaps"] == 1


def test_quota_info_parses_google_errors() -> None:
    class FakeError(Exception):
        details: ClassVar[dict[str, object]] = {
            "error": {
                "code": 429,
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                     "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7.5s"},
                ],
            }
        }  # fmt: skip

    assert quota_info(FakeError()) == (7.5, True)
