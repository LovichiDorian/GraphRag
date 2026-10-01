"""Multi-agent orchestration: planner → graph retriever (+ optional Cypher) → synthesizer.

Each stage is a separate, stateless LLM call, so any model of the fallback
chain can serve any stage, costs are bounded (2 generations + 1 embedding
call per question) and every step is streamed to the UI as an agent trace.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from neo4j.exceptions import Neo4jError
from pydantic import BaseModel, Field

from careergraph.agent.cache import AnswerCache
from careergraph.agent.events import (
    AgentEvent,
    DataPart,
    Metadata,
    StepFinished,
    StepStarted,
    TextDelta,
    ThoughtDelta,
)
from careergraph.agent.prompts import (
    CONTINUE_USER,
    OVERVIEW_HINT,
    PLANNER_SYSTEM,
    PLANNER_USER,
    SYNTHESIZER_SYSTEM,
    SYNTHESIZER_USER,
)
from careergraph.graph.schema import SCHEMA_DESCRIPTION, NodeType
from careergraph.graph.snapshot import GraphSnapshot, normalize_name
from careergraph.graph.store import Neo4jStore, UnsafeCypherError
from careergraph.llm.gemini import Gemini, LLMStreamInterruptedError, LLMUnavailableError
from careergraph.logs import get_logger
from careergraph.retrieval.hybrid import HybridRetriever, RetrievalResult, Source
from careergraph.settings import Settings
from careergraph.text import CITATION, citation_refs, truncate

log = get_logger(__name__)

Intent = Literal[
    "overview", "experience", "skills", "projects", "education", "fit", "comparison", "contact",
    "logistics", "meta", "other",
]  # fmt: skip


class Plan(BaseModel):
    language: str = Field(description="ISO 639-1 code of the visitor's latest message")
    standalone_question: str
    intent: Intent
    search_queries: list[str] = Field(description="1 to 3 short retrieval queries")
    entities: list[str] = Field(description="canonical entity names, possibly empty")
    needs_overview: bool
    cypher: str | None = Field(default=None, description="optional read-only Cypher, else null")


@dataclass(slots=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    text: str


class CareerAgent:
    def __init__(
        self,
        settings: Settings,
        llm: Gemini,
        store: Neo4jStore,
        retriever: HybridRetriever,
        snapshot: Callable[[], GraphSnapshot],
        revision: Callable[[], str] | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.store = store
        self.retriever = retriever
        self._snapshot = snapshot
        self._revision = revision or (lambda: snapshot().version)
        self.cache = AnswerCache(settings.answer_cache_ttl_s, store)
        self._catalog: tuple[str, str] | None = None

    @property
    def snapshot(self) -> GraphSnapshot:
        return self._snapshot()

    # ── planner ───────────────────────────────────────────────────────────────
    def catalog(self) -> str:
        snapshot = self.snapshot
        if self._catalog and self._catalog[0] == snapshot.version:
            return self._catalog[1]
        lines = []
        for node_type in (
            NodeType.ROLE, NodeType.ORGANIZATION, NodeType.PROJECT, NodeType.SKILL, NodeType.DOMAIN,
            NodeType.DEGREE, NodeType.AWARD, NodeType.LANGUAGE, NodeType.LOCATION,
        ):  # fmt: skip
            entities = sorted(snapshot.by_type(node_type), key=lambda e: -e.pagerank)
            if entities:
                names = ", ".join(e.name for e in entities[:160])
                lines.append(f"{node_type.value}: {names}")
        text = truncate("\n".join(lines), 9000)
        self._catalog = (snapshot.version, text)
        return text

    def _heuristic_plan(self, question: str) -> Plan:
        broad = bool(
            re.search(r"\b(who|summary|overview|strengths?|profil|qui est|résumé)\b", question, re.I)
        )
        return Plan(
            language="fr"
            if re.search(r"\b(quel|quelle|est-ce|expérience|compétences|projets)\b", question, re.I)
            else "en",
            standalone_question=question,
            intent="overview" if broad else "other",
            search_queries=[question],
            entities=[],
            needs_overview=broad,
            cypher=None,
        )

    async def plan(self, question: str, history: Sequence[ChatTurn]) -> tuple[Plan, str | None]:
        if not self.llm.enabled:
            return self._heuristic_plan(question), None
        try:
            plan, model = await self.llm.generate_json(
                models=self.settings.fast_models,
                system=PLANNER_SYSTEM.format(schema=SCHEMA_DESCRIPTION, catalog=self.catalog()),
                prompt=PLANNER_USER.format(history=_format_history(history), question=question),
                schema=Plan,
                temperature=0.0,
                thinking="minimal",
            )
        except LLMUnavailableError as exc:
            log.warning("planner.unavailable", error=str(exc)[:200])
            return self._heuristic_plan(question), None
        plan.search_queries = [q for q in plan.search_queries if q.strip()][:3] or [plan.standalone_question]
        plan.entities = plan.entities[:10]
        return plan, model

    # ── main loop ─────────────────────────────────────────────────────────────
    async def run(self, question: str, history: Sequence[ChatTurn]) -> AsyncIterator[AgentEvent]:
        started = time.perf_counter()
        snapshot = self.snapshot
        cache_key = normalize_name(question) if not history else None
        revision = self._revision()
        if cache_key and (cached := await self.cache.get(cache_key, revision)):
            async for event in _replay(cached):
                yield event
            yield Metadata({"cached": True, "latencyMs": _ms(started), "graphVersion": snapshot.version})
            return

        recorded: list[AgentEvent] = []

        def record(event: AgentEvent) -> AgentEvent:
            recorded.append(event)
            return event

        # 1 ─ plan
        yield record(StepStarted("plan", "planner", "Planning the graph search", {"question": question}))
        plan, planner_model = await self.plan(question, history)
        yield record(
            StepFinished(
                "plan",
                {
                    "intent": plan.intent,
                    "language": plan.language,
                    "queries": plan.search_queries,
                    "entities": plan.entities,
                    "cypher": plan.cypher,
                    "model": planner_model or "heuristic",
                },
            )
        )

        # 2 ─ retrieve (+ optional Cypher, in parallel)
        yield record(
            StepStarted(
                "retrieve",
                "graph_retriever",
                "Hybrid search + Personalized PageRank",
                {"queries": plan.search_queries, "entities": plan.entities},
            )
        )
        cypher_task = asyncio.create_task(self._run_cypher(plan.cypher)) if plan.cypher else None
        result = await self.retriever.retrieve(
            plan.search_queries,
            plan.entities,
            include_communities=plan.needs_overview or plan.intent in {"overview", "fit", "skills"},
        )
        yield record(DataPart("graph", result.graph_payload(snapshot), id="graph"))
        yield record(
            StepFinished(
                "retrieve",
                {
                    "entities": [snapshot.entities[e].name for e in result.focus[:10]],
                    "passages": sum(1 for s in result.sources if s.kind == "passage"),
                    "themes": sum(1 for s in result.sources if s.kind == "community"),
                    "timingsMs": result.timings_ms,
                },
            )
        )
        cypher_rows: list[dict[str, Any]] | None = None
        if cypher_task is not None:
            yield record(
                StepStarted("cypher", "cypher_query", "Read-only Cypher query", {"cypher": plan.cypher})
            )
            cypher_rows, cypher_error = await cypher_task
            if cypher_error:
                yield record(StepFinished("cypher", error=cypher_error))
            else:
                yield record(
                    StepFinished(
                        "cypher", {"rows": (cypher_rows or [])[:12], "count": len(cypher_rows or [])}
                    )
                )

        # 3 ─ synthesize (streamed)
        context = self._build_context(
            result, cypher_rows, overview=plan.needs_overview or plan.intent == "overview"
        )
        answer_parts: list[str] = []
        model_used: str | None = None
        degraded = result.degraded
        system = SYNTHESIZER_SYSTEM.format(
            language=plan.language, today=datetime.now(UTC).strftime("%B %d, %Y")
        )
        prompt = SYNTHESIZER_USER.format(
            context=context, history=_format_history(history), question=plan.standalone_question
        )
        interruptions = 0
        while True:
            # After a mid-stream failure, another model continues the partial answer seamlessly.
            contents = (
                prompt
                if not answer_parts
                else CONTINUE_USER.format(prompt=prompt, partial="".join(answer_parts))
            )
            try:
                async for delta in self.llm.stream_text(
                    models=self.settings.chat_models,
                    system=system,
                    contents=contents,
                    temperature=0.3,
                    thinking="low",
                    include_thoughts=not answer_parts,
                ):
                    if delta.kind == "model":
                        model_used = delta.text
                    elif delta.kind == "thought":
                        yield record(ThoughtDelta(delta.text))
                    else:
                        answer_parts.append(delta.text)
                        yield record(TextDelta(delta.text))
                break
            except LLMStreamInterruptedError as exc:
                interruptions += 1
                log.warning("synthesizer.interrupted", attempt=interruptions, error=str(exc)[:160])
                if interruptions <= 2:
                    continue
                degraded = True
                note = _extractive_answer(result, plan.language, partial="".join(answer_parts))
                answer_parts.append(note)
                yield record(TextDelta(note))
                break
            except LLMUnavailableError as exc:
                log.warning("synthesizer.unavailable", error=str(exc)[:200])
                degraded = True
                fallback = _extractive_answer(result, plan.language, partial="".join(answer_parts))
                answer_parts.append(fallback)
                yield record(TextDelta(fallback))
                break

        # 4 ─ citations, evidence graph, follow-ups
        answer = "".join(answer_parts)
        cited = citation_refs(answer)
        sources = [{**s.public(), "cited": s.ref in cited} for s in result.sources]
        yield record(DataPart("sources", {"sources": sources}, id="sources"))
        emphasis = [eid for s in result.sources if s.ref in cited for eid in s.entity_ids]
        yield record(DataPart("graph", result.graph_payload(snapshot, emphasis), id="graph"))
        yield record(
            DataPart("followups", {"questions": self._followups(plan, result, question)}, id="followups")
        )

        meta = {
            "model": model_used,
            "plannerModel": planner_model,
            "latencyMs": _ms(started),
            "retrievalMs": result.timings_ms.get("total"),
            "degraded": degraded,
            "cached": False,
            "graphVersion": snapshot.version,
        }
        yield Metadata(meta)
        if cache_key and not degraded and answer.strip():
            await self.cache.put(cache_key, revision, recorded)

    async def answer(self, question: str, history: Sequence[ChatTurn] = ()) -> dict[str, Any]:
        """Non-streaming variant (used by the MCP server)."""
        text: list[str] = []
        sources: list[dict[str, Any]] = []
        meta: dict[str, Any] = {}
        async for event in self.run(question, history):
            if isinstance(event, TextDelta):
                text.append(event.text)
            elif isinstance(event, DataPart) and event.name == "sources":
                sources = [s for s in event.data["sources"] if s.get("cited")]
            elif isinstance(event, Metadata):
                meta.update(event.data)
        return {"answer": "".join(text), "sources": sources, "model": meta.get("model")}

    # ── helpers ───────────────────────────────────────────────────────────────
    async def _run_cypher(self, cypher: str | None) -> tuple[list[dict[str, Any]] | None, str | None]:
        if not cypher:
            return None, None
        try:
            return await self.store.run_readonly_cypher(cypher, limit=25), None
        except UnsafeCypherError as exc:
            return None, f"Rejected by the read-only guard: {exc}"
        except Neo4jError as exc:
            return None, f"Cypher error: {truncate(exc.message or str(exc), 200)}"

    def _build_context(
        self, result: RetrievalResult, cypher_rows: list[dict[str, Any]] | None, *, overview: bool
    ) -> str:
        blocks: list[str] = []
        if overview and (person := self._person()):
            blocks.append(
                "## Profile\n"
                + OVERVIEW_HINT.format(
                    headline=person.props.get("headline", ""),
                    location=person.props.get("location", ""),
                    work_authorization=person.props.get("work_authorization", ""),
                    summary=person.description,
                )
            )
        passages = [s for s in result.sources if s.kind == "passage"]
        entities = [s for s in result.sources if s.kind == "entity"]
        themes = [s for s in result.sources if s.kind == "community"]
        if passages:
            blocks.append("## Evidence passages\n" + "\n\n".join(_render_source(s, 1400) for s in passages))
        if entities:
            blocks.append(
                "## Knowledge-graph entities\n" + "\n\n".join(_render_source(s, 1100) for s in entities)
            )
        if themes:
            blocks.append(
                "## Thematic summaries (graph communities)\n"
                + "\n\n".join(_render_source(s, 800) for s in themes)
            )
        if cypher_rows:
            rows = "\n".join(f"- {truncate(str(row), 300)}" for row in cypher_rows[:25])
            blocks.append(f"## Cypher query results (exact, from the graph)\n{rows}")
        if result.edges:
            snapshot = self.snapshot
            triples = [
                f"- {snapshot.entities[e.source].name} —{e.type}→ {snapshot.entities[e.target].name}"
                for e in result.edges[:40]
            ]
            blocks.append("## Relations between the retrieved entities\n" + "\n".join(triples))
        return "\n\n".join(blocks) or "(no relevant context found)"

    def _person(self) -> Any:
        people = self.snapshot.by_type(NodeType.PERSON)
        return people[0] if people else None

    def _followups(self, plan: Plan, result: RetrievalResult, question: str) -> list[str]:
        snapshot = self.snapshot
        fr = plan.language.startswith("fr")
        asked = normalize_name(question)
        suggestions: list[str] = []
        for eid in result.focus:
            entity = snapshot.entities[eid]
            if normalize_name(entity.name) in asked:
                continue
            if entity.type == NodeType.PROJECT and len(suggestions) < 2:
                suggestions.append(
                    f"Qu'a construit Dorian dans {entity.name} ?"
                    if fr
                    else f"What did Dorian build in {entity.name}?"
                )
            elif entity.type == NodeType.SKILL and entity.props.get("category") not in {
                "concept",
                "practice",
            }:
                suggestions.append(
                    f"Où Dorian a-t-il utilisé {entity.name} ?"
                    if fr
                    else f"Where has Dorian used {entity.name}?"
                )
            if len(suggestions) >= 2:
                break
        if plan.intent != "fit":
            suggestions.append(
                "Dorian correspond-il à un poste d'AI Engineer ?"
                if fr
                else "Is Dorian a good fit for an AI Engineer role?"
            )
        return list(dict.fromkeys(suggestions))[:3]


def _render_source(source: Source, max_chars: int) -> str:
    link = f" ({source.url})" if source.url else ""
    return f"[{source.ref}] {source.title}{link}\n{truncate(source.text, max_chars)}"


def _format_history(history: Sequence[ChatTurn], max_turns: int = 6) -> str:
    if not history:
        return "(none)"
    lines = []
    for turn in list(history)[-max_turns:]:
        who = "Visitor" if turn.role == "user" else "Assistant"
        lines.append(f"{who}: {truncate(CITATION.sub('', turn.text), 700)}")
    return "\n".join(lines)


def _extractive_answer(result: RetrievalResult, language: str, *, partial: str = "") -> str:
    """Evidence bullets shown when no model can answer (``partial``: text streamed so far)."""
    fr = language.startswith("fr")
    header = (
        "\n\n_Le modèle de langage est momentanément indisponible — voici les éléments les plus pertinents du graphe :_\n\n"
        if fr
        else "\n\n_The language model is temporarily unavailable — here are the most relevant facts from the graph:_\n\n"
    )
    if not partial.strip():
        header = header.lstrip()
    elif not partial.rstrip().endswith((".", "!", "?", "…", ":", ")", "]")):
        header = "…" + header  # the model stopped mid-sentence
    bullets = [
        f"- **{s.title}** — {truncate(' '.join(s.text.split()), 260)} [{s.ref}]"
        for s in result.sources
        if s.kind in {"passage", "entity"}
    ][:6]
    return header + ("\n".join(bullets) if bullets else "_No matching evidence found._")


async def _replay(events: list[AgentEvent]) -> AsyncIterator[AgentEvent]:
    """Replay a cached answer with a light streaming cadence."""
    for event in events:
        if isinstance(event, TextDelta) and len(event.text) > 40:
            for i in range(0, len(event.text), 40):
                yield TextDelta(event.text[i : i + 40])
                await asyncio.sleep(0.008)
        else:
            yield event


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)
