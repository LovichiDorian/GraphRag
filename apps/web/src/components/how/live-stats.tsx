"use client";

import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PALETTES } from "@/lib/graph-style";
import { useTheme } from "@/lib/theme";
import type { NodeType, Stats } from "@/lib/types";

export function LiveStats() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [failed, setFailed] = useState(false);
  const theme = useTheme();
  useEffect(() => {
    api
      .stats()
      .then(setStats)
      .catch(() => setFailed(true));
  }, []);

  if (failed)
    return (
      <div className="glass-soft rounded-2xl p-5 text-sm text-fg-muted">Stats are unavailable right now.</div>
    );
  if (!stats) return <div className="glass-soft h-72 animate-pulse rounded-2xl" />;

  const { graph } = stats;
  const types = Object.entries(graph.entitiesByType);
  const max = Math.max(...types.map(([, n]) => n), 1);
  const tiles = [
    ["Entities", graph.entities],
    ["Relations", graph.relations],
    ["Evidence chunks", graph.chunks ?? "—"],
    ["Themes", graph.communities ?? "—"],
    ["Repositories", graph.repositories ?? "—"],
    ["Documents", graph.documents ?? "—"],
  ] as const;

  return (
    <div className="glass-soft rounded-2xl p-5">
      <div className="grid grid-cols-3 gap-3">
        {tiles.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-tint/[0.06] bg-tint/[0.02] p-3">
            <div className="text-2xl font-semibold tracking-tight text-fg">{value}</div>
            <div className="text-[11px] text-fg-subtle">{label}</div>
          </div>
        ))}
      </div>
      <div className="mt-5 grid gap-1.5">
        {types.map(([type, count]) => (
          <div key={type} className="grid grid-cols-[96px_1fr_32px] items-center gap-2 text-xs">
            <span className="text-fg-muted">{type}</span>
            <div className="h-1.5 overflow-hidden rounded-full bg-tint/[0.06]">
              <motion.div
                className="h-full rounded-full"
                style={{ background: PALETTES[theme].types[type as NodeType] ?? "#94a3b8" }}
                initial={{ width: 0 }}
                animate={{ width: `${(100 * count) / max}%` }}
                transition={{ duration: 0.8 }}
              />
            </div>
            <span className="text-right font-mono text-fg-muted">{count}</span>
          </div>
        ))}
      </div>
      <div className="mt-5 grid gap-1 border-t border-tint/[0.06] pt-4 text-xs text-fg-subtle">
        <div>
          Chat models: <span className="text-fg-soft">{stats.models.chat.slice(0, 3).join(" → ")}…</span>
        </div>
        <div>
          Embeddings: <span className="text-fg-soft">{stats.models.embedding}</span>
        </div>
        <div>
          Graph version <span className="font-mono text-fg-soft">{graph.version}</span>
          {graph.builtAt ? ` · built ${new Date(graph.builtAt).toLocaleString()}` : ""}
          {graph.ingestionSeconds ? ` in ${graph.ingestionSeconds}s` : ""}
        </div>
      </div>
    </div>
  );
}
