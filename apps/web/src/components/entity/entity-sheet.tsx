"use client";

import { ArrowLeft, ExternalLink, LoaderCircle, MessageSquareText } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { nodeColor, TYPE_LABELS } from "@/lib/graph-style";
import { useUI } from "@/lib/store";
import { useTheme } from "@/lib/theme";
import type { EntityDetails, NodeType } from "@/lib/types";
import { hostOf } from "@/lib/utils";
import { Dot } from "../ui/badge";
import { Button } from "../ui/button";

function questionFor(type: NodeType, name: string) {
  switch (type) {
    case "Skill":
      return `How has Dorian used ${name}?`;
    case "Project":
      return `What did Dorian build in ${name}, and with which technologies?`;
    case "Role":
      return `What did Dorian achieve as ${name}?`;
    case "Organization":
      return `What is Dorian's experience with ${name}?`;
    case "Domain":
      return `How strong is Dorian in ${name}?`;
    default:
      return `Tell me about ${name} in Dorian's background.`;
  }
}

export function EntitySheet({ id }: { id: string }) {
  const select = useUI((s) => s.select);
  const ask = useUI((s) => s.ask);
  const setHighlight = useUI((s) => s.setHighlight);
  const [details, setDetails] = useState<EntityDetails | null>(null);
  const [failed, setFailed] = useState(false);
  const theme = useTheme();

  useEffect(() => {
    let cancelled = false;
    setDetails(null);
    setFailed(false);
    api
      .node(id)
      .then((data) => {
        if (cancelled) return;
        setDetails(data);
        const neighbours = Object.values(data.relations)
          .flat()
          .map((r) => r.id);
        setHighlight({
          nodes: [id, ...neighbours],
          links: neighbours.flatMap((n) => [
            { source: id, target: n, type: "" },
            { source: n, target: id, type: "" },
          ]),
          seeds: [id],
          emphasis: [id],
        });
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [id, setHighlight]);

  const entity = details?.entity;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-tint/[0.06] px-3 py-2.5">
        <Button variant="ghost" size="sm" onClick={() => select(null)} aria-label="Back">
          <ArrowLeft /> Back
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4 scrollbar-thin">
        {!details && !failed && (
          <div className="flex items-center gap-2 text-sm text-fg-muted">
            <LoaderCircle className="size-4 animate-spin" /> Loading…
          </div>
        )}
        {failed && <p className="text-sm text-fg-muted">Could not load this entity.</p>}
        {entity && details && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex flex-col gap-4"
          >
            <div>
              <div className="mb-1.5 flex items-center gap-2 text-[11px] uppercase tracking-wider text-fg-muted">
                <Dot
                  color={nodeColor(
                    { type: entity.type, name: entity.name, category: entity.category },
                    theme,
                  )}
                />
                {entity.type}
                {entity.category ? ` · ${entity.category}` : ""}
              </div>
              <h2 className="text-xl font-semibold tracking-tight text-fg">{entity.name}</h2>
              {entity.period || entity.start ? (
                <div className="mt-0.5 text-xs text-fg-subtle">{entity.period ?? entity.start}</div>
              ) : null}
              {entity.description && (
                <p className="mt-2 text-sm leading-relaxed text-fg-soft">{entity.description}</p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => ask(questionFor(entity.type, entity.name))}
                >
                  <MessageSquareText /> Ask about this
                </Button>
                {(entity.repo_url || entity.url) && (
                  <Button variant="outline" size="sm" asChild>
                    <a href={String(entity.repo_url ?? entity.url)} target="_blank" rel="noreferrer">
                      <ExternalLink /> {hostOf(String(entity.repo_url ?? entity.url))}
                    </a>
                  </Button>
                )}
              </div>
            </div>

            {Array.isArray(entity.highlights) && entity.highlights.length > 0 && (
              <ul className="grid gap-1.5 rounded-xl border border-tint/[0.06] bg-tint/[0.02] p-3 text-xs leading-relaxed text-fg-soft">
                {entity.highlights.map((h) => (
                  <li key={h} className="flex gap-2">
                    <span className="mt-1.5 size-1 shrink-0 rounded-full bg-cyan-300" />
                    {h}
                  </li>
                ))}
              </ul>
            )}

            {entity.type === "Skill" && entity.strength != null && (
              <div className="rounded-xl border border-tint/[0.06] bg-tint/[0.02] p-3 text-xs">
                <div className="mb-1.5 flex justify-between text-fg-muted">
                  <span>Evidence strength</span>
                  <span>
                    {entity.evidence ?? 0} role/project{entity.evidence === 1 ? "" : "s"}
                    {entity.last_used ? ` · last used ${entity.last_used}` : ""}
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-tint/10">
                  <motion.div
                    className="h-full rounded-full bg-gradient-to-r from-violet-500 to-cyan-400"
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.round(Number(entity.strength) * 100)}%` }}
                  />
                </div>
              </div>
            )}

            {Object.entries(details.relations).map(([label, items]) => (
              <section key={label}>
                <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-fg-subtle">
                  {label} <span className="text-fg-faint">· {items.length}</span>
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {items.slice(0, 40).map((item) => (
                    <button
                      key={`${label}-${item.id}`}
                      type="button"
                      onClick={() => select(item.id)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-tint/[0.07] bg-tint/[0.03] px-2 py-1 text-xs text-fg-soft transition hover:border-violet-400/40 hover:text-fg"
                    >
                      <Dot
                        color={nodeColor({ type: item.type, name: item.name }, theme)}
                        className="size-1.5"
                      />
                      {item.name}
                    </button>
                  ))}
                </div>
              </section>
            ))}

            {details.evidence.length > 0 && (
              <section>
                <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-fg-subtle">
                  Evidence
                </h3>
                <div className="grid gap-2">
                  {details.evidence.map((ev) => (
                    <div
                      key={ev.id}
                      className="rounded-xl border border-tint/[0.06] bg-tint/[0.02] p-3 text-xs"
                    >
                      <div className="mb-1 font-medium text-fg-soft">
                        {ev.url ? (
                          <a href={ev.url} target="_blank" rel="noreferrer" className="hover:underline">
                            {ev.doc_title}
                          </a>
                        ) : (
                          ev.doc_title
                        )}
                      </div>
                      <p className="line-clamp-4 leading-relaxed text-fg-muted">{ev.text}</p>
                    </div>
                  ))}
                </div>
              </section>
            )}
            <p className="text-[10px] text-fg-faint">
              {TYPE_LABELS[entity.type]} node · id {entity.id}
            </p>
          </motion.div>
        )}
      </div>
    </div>
  );
}
