"use client";

import type { DynamicToolUIPart } from "ai";
import {
  Brain,
  Check,
  ChevronDown,
  CircleAlert,
  Database,
  LoaderCircle,
  Network,
  Route,
  Sparkles,
  Zap,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import type { ChatMessage } from "@/lib/chat-types";
import { useUI } from "@/lib/store";
import type { GraphHighlight, SourceRef } from "@/lib/types";
import { cn, formatMs } from "@/lib/utils";
import { Markdown } from "./markdown";
import { SourceIcon, sourceLabel } from "./source-icon";

const STEP_META: Record<string, { icon: typeof Route; label: string }> = {
  planner: { icon: Route, label: "Planner agent" },
  graph_retriever: { icon: Network, label: "Graph retriever" },
  cypher_query: { icon: Database, label: "Cypher" },
};

function stepSummary(part: DynamicToolUIPart): string {
  if (part.state === "output-error") return part.errorText ?? "failed";
  if (part.state !== "output-available") return part.title ?? "working…";
  const out = (part.output ?? {}) as Record<string, unknown>;
  switch (part.toolName) {
    case "planner": {
      const queries = (out.queries as string[] | undefined)?.length ?? 0;
      return `intent: ${out.intent} · ${queries} quer${queries === 1 ? "y" : "ies"}${out.cypher ? " · Cypher" : ""}`;
    }
    case "graph_retriever": {
      const entities = (out.entities as string[] | undefined) ?? [];
      return `${entities.length} entities · ${out.passages} passages${out.themes ? ` · ${out.themes} themes` : ""}`;
    }
    case "cypher_query":
      return `${out.count} row${out.count === 1 ? "" : "s"}`;
    default:
      return "done";
  }
}

export function AgentTrace({ parts, streaming }: { parts: DynamicToolUIPart[]; streaming: boolean }) {
  const [open, setOpen] = useState(false);
  if (!parts.length) return null;
  const done = parts.every((p) => p.state === "output-available" || p.state === "output-error");
  return (
    <div className="mb-3 rounded-xl border border-tint/[0.06] bg-tint/[0.02] text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-fg-muted hover:text-fg-soft"
      >
        <Zap className="size-3.5 text-violet-600 dark:text-violet-300" />
        <span className={cn(!done && streaming && "shimmer-text")}>
          {done ? "Agentic GraphRAG pipeline" : "Agents at work…"}
        </span>
        <span className="ml-auto flex items-center gap-1">
          {parts.map((p) => {
            const Icon = STEP_META[p.toolName]?.icon ?? Sparkles;
            return (
              <Icon
                key={p.toolCallId}
                className={cn(
                  "size-3.5",
                  p.state === "output-available"
                    ? "text-emerald-600 dark:text-emerald-300"
                    : p.state === "output-error"
                      ? "text-amber-700 dark:text-amber-300"
                      : "animate-pulse text-fg-subtle",
                )}
              />
            );
          })}
          <ChevronDown className={cn("size-3.5 transition", open && "rotate-180")} />
        </span>
      </button>
      <AnimatePresence initial={false}>
        {(open || (!done && streaming)) && (
          <motion.ol
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden px-3 pb-2.5"
          >
            {parts.map((part) => {
              const meta = STEP_META[part.toolName] ?? { icon: Sparkles, label: part.toolName };
              const running = part.state !== "output-available" && part.state !== "output-error";
              const output = (part.output ?? {}) as Record<string, unknown>;
              return (
                <li key={part.toolCallId} className="relative flex gap-2.5 py-1.5 pl-0.5">
                  <span className="mt-0.5 grid size-4 place-items-center">
                    {running ? (
                      <LoaderCircle className="size-3.5 animate-spin text-violet-600 dark:text-violet-300" />
                    ) : part.state === "output-error" ? (
                      <CircleAlert className="size-3.5 text-amber-700 dark:text-amber-300" />
                    ) : (
                      <Check className="size-3.5 text-emerald-600 dark:text-emerald-300" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 text-fg-soft">
                      <meta.icon className="size-3 text-fg-subtle" />
                      {meta.label}
                      <span className="truncate text-fg-subtle">— {stepSummary(part)}</span>
                    </div>
                    {part.toolName === "graph_retriever" && Array.isArray(output.entities) && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {(output.entities as string[]).slice(0, 8).map((name) => (
                          <span
                            key={name}
                            className="rounded border border-tint/[0.07] px-1.5 py-px text-[10px] text-fg-muted"
                          >
                            {name}
                          </span>
                        ))}
                      </div>
                    )}
                    {part.toolName === "cypher_query" && (
                      <pre className="mt-1 overflow-x-auto rounded-md bg-ink-900 p-2 font-mono text-[10px] leading-relaxed text-cyan-200/90 scrollbar-thin">
                        {String((part.input as { cypher?: string } | undefined)?.cypher ?? "")}
                      </pre>
                    )}
                  </div>
                </li>
              );
            })}
          </motion.ol>
        )}
      </AnimatePresence>
    </div>
  );
}

function Reasoning({ text, streaming }: { text: string; streaming: boolean }) {
  const [open, setOpen] = useState(false);
  if (!text.trim()) return null;
  return (
    <div className="mb-3 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-fg-subtle hover:text-fg-soft"
      >
        <Brain className="size-3.5" />
        <span className={cn(streaming && "shimmer-text")}>{streaming ? "Thinking…" : "Model reasoning"}</span>
        <ChevronDown className={cn("size-3.5 transition", open && "rotate-180")} />
      </button>
      {open && (
        <div className="mt-2 whitespace-pre-wrap border-l border-violet-400/30 pl-3 text-fg-muted italic">
          {text}
        </div>
      )}
    </div>
  );
}

function Sources({ sources }: { sources: SourceRef[] }) {
  const [all, setAll] = useState(false);
  const setHighlight = useUI((s) => s.setHighlight);
  const cited = sources.filter((s) => s.cited);
  const list = all ? sources : cited.length ? cited : sources.slice(0, 4);
  if (!sources.length) return null;
  return (
    <div className="mt-3 border-t border-tint/[0.06] pt-3">
      <div className="mb-2 flex items-center justify-between text-[11px] uppercase tracking-wider text-fg-subtle">
        <span>Evidence · {cited.length || list.length} cited</span>
        {sources.length > list.length || all ? (
          <button
            type="button"
            className="normal-case tracking-normal text-fg-muted hover:text-fg"
            onClick={() => setAll((v) => !v)}
          >
            {all ? "Cited only" : `All ${sources.length}`}
          </button>
        ) : null}
      </div>
      <ul className="grid gap-1.5">
        {list.map((source) => (
          <li
            key={source.ref}
            className="group flex items-start gap-2 rounded-lg border border-tint/[0.05] bg-tint/[0.02] px-2.5 py-2 text-xs transition hover:border-violet-400/30 hover:bg-violet-500/[0.06]"
            onMouseEnter={() =>
              source.entityIds.length &&
              setHighlight({ nodes: source.entityIds, links: [], seeds: [], emphasis: source.entityIds })
            }
          >
            <span className="mt-px font-mono text-[10px] text-violet-600 dark:text-violet-300">
              {source.ref}
            </span>
            <SourceIcon source={source} className="mt-0.5 size-3.5 shrink-0 text-fg-muted" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-fg-soft">
                {source.url ? (
                  <a href={source.url} target="_blank" rel="noreferrer" className="hover:underline">
                    {source.title}
                  </a>
                ) : (
                  source.title
                )}
              </div>
              <div className="text-[10px] text-fg-subtle">{sourceLabel(source)}</div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AssistantMessage({
  message,
  streaming,
  isLast,
  onFollowup,
}: {
  message: ChatMessage;
  streaming: boolean;
  isLast: boolean;
  onFollowup: (q: string) => void;
}) {
  const setHighlight = useUI((s) => s.setHighlight);
  const { steps, reasoning, text, sources, followups, graph } = useMemo(() => {
    const steps: DynamicToolUIPart[] = [];
    let reasoning = "";
    let text = "";
    let sources: SourceRef[] = [];
    let followups: string[] = [];
    let graph: GraphHighlight | null = null;
    for (const part of message.parts) {
      if (part.type === "dynamic-tool") steps.push(part);
      else if (part.type === "reasoning") reasoning += part.text;
      else if (part.type === "text") text += part.text;
      else if (part.type === "data-sources") sources = part.data.sources;
      else if (part.type === "data-followups") followups = part.data.questions;
      else if (part.type === "data-graph") graph = part.data;
    }
    return { steps, reasoning, text, sources, followups, graph };
  }, [message.parts]);
  const meta = message.metadata;

  return (
    <div className="group/msg">
      <AgentTrace parts={steps} streaming={streaming} />
      <Reasoning text={reasoning} streaming={streaming && !text} />
      {text ? (
        <Markdown text={text} sources={sources} />
      ) : streaming ? (
        <div className="flex items-center gap-2 py-1 text-sm text-fg-subtle">
          <span className="size-1.5 animate-bounce rounded-full bg-violet-400 [animation-delay:-0.2s]" />
          <span className="size-1.5 animate-bounce rounded-full bg-violet-400 [animation-delay:-0.1s]" />
          <span className="size-1.5 animate-bounce rounded-full bg-cyan-400" />
        </div>
      ) : null}
      {!streaming && <Sources sources={sources} />}
      {!streaming && (meta?.model || meta?.cached) && (
        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-fg-subtle">
          {meta.cached ? (
            <span className="text-emerald-600/80 dark:text-emerald-400/80">⚡ cached answer</span>
          ) : (
            <span>{meta.model}</span>
          )}
          {meta.latencyMs != null && <span>{formatMs(meta.latencyMs)}</span>}
          {meta.degraded && <span className="text-amber-700/80 dark:text-amber-300/80">degraded mode</span>}
          {graph && (
            <button
              type="button"
              className="text-violet-600 dark:text-violet-300 hover:text-fg"
              onClick={() => setHighlight(graph)}
            >
              Show evidence graph
            </button>
          )}
        </div>
      )}
      {isLast && !streaming && followups.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {followups.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => onFollowup(q)}
              className="rounded-full border border-tint/10 bg-tint/[0.03] px-3 py-1 text-xs text-fg-soft transition hover:border-violet-400/40 hover:bg-violet-500/10 hover:text-fg"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
