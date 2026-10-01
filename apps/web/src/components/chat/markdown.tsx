"use client";

import { memo, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { useUI } from "@/lib/store";
import type { SourceRef } from "@/lib/types";
import { HoverCard } from "../ui/hover-card";
import { SourceIcon, sourceLabel } from "./source-icon";

// Inline citations from the models: "[3]", "[2][5]", "[2, 16, 23]", "[4-6]" (never markdown links).
const CITATION = /\[(\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*)\](?!\()/g;
const INLINE_CODE = /(```[\s\S]*?```|`[^`\n]*`)/g;

function citationNumbers(group: string): number[] {
  const refs: number[] = [];
  for (const piece of group.split(/[,;]/)) {
    const [from = 0, to] = piece.split(/[–-]/).map((n) => Number(n.trim()));
    if (to !== undefined && to > from && to - from <= 12) {
      for (let n = from; n <= to; n++) refs.push(n);
    } else refs.push(from, ...(to === undefined ? [] : [to]));
  }
  return [...new Set(refs)].filter((n) => n > 0);
}

/** Turns citations into `#cite-n` links (rendered as chips), leaving code spans untouched. */
function linkCitations(text: string): string {
  return text
    .split(INLINE_CODE)
    .map((part, i) =>
      i % 2
        ? part
        : part.replace(CITATION, (_, group: string) =>
            citationNumbers(group)
              .map((n) => `[${n}](#cite-${n})`)
              .join(""),
          ),
    )
    .join("");
}

function Citation({ n, source }: { n: number; source?: SourceRef }) {
  const setHighlight = useUI((s) => s.setHighlight);
  const chip = (
    <button
      type="button"
      onClick={() => {
        if (source?.entityIds.length) {
          setHighlight({ nodes: source.entityIds, links: [], seeds: [], emphasis: source.entityIds });
        }
      }}
      className="mx-0.5 inline-flex h-[1.15rem] min-w-[1.15rem] -translate-y-[1px] items-center justify-center rounded-md border border-violet-400/30 bg-violet-500/15 px-1 align-middle font-mono text-[10px] font-semibold text-violet-700 dark:text-violet-200 transition hover:border-cyan-300/60 hover:bg-cyan-400/20 hover:text-fg"
      aria-label={source ? `Source ${n}: ${source.title}` : `Source ${n}`}
    >
      {n}
    </button>
  );
  if (!source) return chip;
  return (
    <HoverCard trigger={chip}>
      <div className="mb-1.5 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-fg-muted">
        <SourceIcon source={source} />
        {sourceLabel(source)}
      </div>
      <div className="mb-1 font-medium text-fg">{source.title}</div>
      <p className="line-clamp-5 text-fg-muted">{source.snippet}</p>
      {source.url ? (
        <a
          href={source.url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-block text-cyan-700 dark:text-cyan-300 hover:underline"
        >
          Open source ↗
        </a>
      ) : null}
    </HoverCard>
  );
}

function MarkdownImpl({ text, sources }: { text: string; sources: SourceRef[] }) {
  const prepared = useMemo(() => linkCitations(text), [text]);
  const byRef = useMemo(() => new Map(sources.map((s) => [s.ref, s])), [sources]);
  const components = useMemo<Components>(
    () => ({
      a: ({ href, children }) => {
        if (href?.startsWith("#cite-")) {
          const n = Number(href.slice(6));
          return <Citation n={n} source={byRef.get(n)} />;
        }
        return (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        );
      },
    }),
    [byRef],
  );
  return (
    <div className="prose-answer">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {prepared}
      </ReactMarkdown>
    </div>
  );
}

export const Markdown = memo(MarkdownImpl);
