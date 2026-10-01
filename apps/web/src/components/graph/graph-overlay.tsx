"use client";

import { Box, Crosshair, Orbit } from "lucide-react";
import { PALETTES, TYPE_LABELS } from "@/lib/graph-style";
import { useUI } from "@/lib/store";
import { useTheme } from "@/lib/theme";
import type { GraphData, NodeType } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Dot } from "../ui/badge";
import { Tooltip } from "../ui/tooltip";

const LEGEND_TYPES: NodeType[] = ["Role", "Organization", "Project", "Degree", "Award", "Language"];

export function GraphOverlay({ data }: { data: GraphData | null }) {
  const mode = useUI((s) => s.mode);
  const setMode = useUI((s) => s.setMode);
  const highlight = useUI((s) => s.highlight);
  const setHighlight = useUI((s) => s.setHighlight);
  const hiddenTypes = useUI((s) => s.hiddenTypes);
  const toggleType = useUI((s) => s.toggleType);
  const palette = PALETTES[useTheme()];
  if (!data) return null;
  const counts = data.nodes.reduce<Record<string, number>>((acc, n) => {
    acc[n.type] = (acc[n.type] ?? 0) + 1;
    return acc;
  }, {});
  const themes = new Set(data.nodes.map((n) => n.community).filter(Boolean)).size;

  return (
    <div className="pointer-events-none absolute inset-x-3 bottom-3 z-10 flex flex-col gap-2 sm:inset-x-5 sm:bottom-5 lg:right-auto lg:max-w-[min(56vw,720px)]">
      <div className="pointer-events-auto flex flex-wrap items-center gap-1.5">
        <div className="glass flex items-center gap-3 rounded-xl px-3 py-2 text-[11px] text-fg-muted">
          <span>
            <b className="font-semibold text-fg">{data.nodes.length}</b> entities
          </span>
          <span>
            <b className="font-semibold text-fg">{data.links.length}</b> relations
          </span>
          <span>
            <b className="font-semibold text-fg">{themes}</b> themes
          </span>
        </div>
        <div className="glass flex items-center rounded-xl p-1">
          <Tooltip content="3D graph (WebGL + bloom)">
            <button
              type="button"
              aria-label="3D graph"
              onClick={() => setMode("3d")}
              className={cn(
                "grid size-7 place-items-center rounded-lg",
                mode === "3d" ? "bg-tint/10 text-fg" : "text-fg-subtle hover:text-fg",
              )}
            >
              <Box className="size-3.5" />
            </button>
          </Tooltip>
          <Tooltip content="2D graph (lighter)">
            <button
              type="button"
              aria-label="2D graph"
              onClick={() => setMode("2d")}
              className={cn(
                "grid size-7 place-items-center rounded-lg",
                mode === "2d" ? "bg-tint/10 text-fg" : "text-fg-subtle hover:text-fg",
              )}
            >
              <Orbit className="size-3.5" />
            </button>
          </Tooltip>
          {highlight && (
            <Tooltip content="Clear the evidence highlight">
              <button
                type="button"
                aria-label="Reset view"
                onClick={() => setHighlight(null)}
                className="grid size-7 place-items-center rounded-lg text-fg-muted hover:text-fg"
              >
                <Crosshair className="size-3.5" />
              </button>
            </Tooltip>
          )}
        </div>
      </div>
      <div className="pointer-events-auto glass hidden flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl px-3 py-2 text-[11px] text-fg-muted sm:flex">
        {LEGEND_TYPES.filter((t) => counts[t]).map((type) => (
          <button
            key={type}
            type="button"
            onClick={() => toggleType(type)}
            className={cn(
              "flex items-center gap-1.5 transition hover:text-fg",
              hiddenTypes.includes(type) && "opacity-35",
            )}
          >
            <Dot color={palette.types[type]} />
            {TYPE_LABELS[type]}
          </button>
        ))}
        <span className="h-3 w-px bg-tint/10" />
        <span className="text-fg-subtle">Skills by domain:</span>
        {Object.entries(palette.domains).map(([domain, color]) => (
          <span key={domain} className="flex items-center gap-1.5">
            <Dot color={color} className="size-1.5" />
            {domain}
          </span>
        ))}
      </div>
    </div>
  );
}
