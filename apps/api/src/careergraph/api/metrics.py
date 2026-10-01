"""Prometheus metrics: HTTP RED metrics plus a collector exposing LLM/graph state."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterator
from typing import TYPE_CHECKING

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

if TYPE_CHECKING:
    from careergraph.services import Services

REGISTRY = CollectorRegistry()
HTTP_REQUESTS = Counter(
    "careergraph_http_requests_total", "HTTP requests", ["route", "method", "status"], registry=REGISTRY
)
HTTP_LATENCY = Histogram(
    "careergraph_http_request_duration_seconds",
    "HTTP request latency (time to response headers for streams)",
    ["route", "method"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    registry=REGISTRY,
)
RATE_LIMITED = Counter(
    "careergraph_rate_limited_total", "Requests rejected by the rate limiter", registry=REGISTRY
)


class ServicesCollector(Collector):
    def __init__(self, services: Services) -> None:
        self.services = services

    def collect(self) -> Iterator[GaugeMetricFamily | CounterMetricFamily]:
        s = self.services
        llm_requests = CounterMetricFamily(
            "careergraph_llm_requests", "Successful LLM calls", labels=["model"]
        )
        llm_failures = CounterMetricFamily("careergraph_llm_failures", "Failed LLM calls", labels=["model"])
        for model, count in s.llm.stats.requests.items():
            llm_requests.add_metric([model], count)
        for model, count in s.llm.stats.failures.items():
            llm_failures.add_metric([model], count)
        yield llm_requests
        yield llm_failures
        tokens = CounterMetricFamily("careergraph_llm_tokens", "LLM tokens", labels=["kind"])
        tokens.add_metric(["input"], s.llm.stats.input_tokens)
        tokens.add_metric(["output"], s.llm.stats.output_tokens)
        tokens.add_metric(["thoughts"], s.llm.stats.thought_tokens)
        yield tokens
        yield GaugeMetricFamily(
            "careergraph_llm_budget_remaining", "Remaining daily LLM calls", value=s.llm.budget.remaining
        )
        cache = CounterMetricFamily("careergraph_answer_cache", "Answer cache lookups", labels=["result"])
        cache.add_metric(["hit"], s.agent.cache.hits)
        cache.add_metric(["miss"], s.agent.cache.misses)
        yield cache
        nodes = GaugeMetricFamily(
            "careergraph_graph_entities", "Entities in the loaded graph", labels=["type"]
        )
        counts: dict[str, int] = {}
        for entity in s.snapshot().entities.values():
            counts[entity.type] = counts.get(entity.type, 0) + 1
        for node_type, count in counts.items():
            nodes.add_metric([node_type], count)
        yield nodes
        yield GaugeMetricFamily(
            "careergraph_graph_relations", "Relations in the loaded graph", value=len(s.snapshot().edges)
        )
        yield GaugeMetricFamily("careergraph_neo4j_up", "Neo4j reachable", value=1 if s.neo4j_ready else 0)


def route_template(request: Request) -> str:
    for route in request.app.router.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", request.url.path)
    return "unmatched"


async def metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path in {"/metrics", "/healthz", "/readyz"}:
        return await call_next(request)
    route = route_template(request)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        HTTP_LATENCY.labels(route, request.method).observe(time.perf_counter() - started)
        HTTP_REQUESTS.labels(route, request.method, str(status)).inc()
