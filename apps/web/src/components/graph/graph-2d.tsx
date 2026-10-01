"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { isLandmark, nodeColor, nodeRadius } from "@/lib/graph-style";
import { type Theme, useTheme } from "@/lib/theme";
import type { GraphData, GraphLink, GraphNode } from "@/lib/types";
import { linkKey, useGraphFocus } from "./use-graph-focus";

interface Props {
  data: GraphData;
  width: number;
  height: number;
  onNodeClick: (node: GraphNode) => void;
}

const INK: Record<
  Theme,
  { label: string; labelStrong: string; ring: string; link: string; linkFocus: string; particle: string }
> = {
  dark: {
    label: "#cbd5e1",
    labelStrong: "#ffffff",
    ring: "rgba(4,5,10,0.9)",
    link: "rgba(100,116,139,0.18)",
    linkFocus: "rgba(165,180,252,0.9)",
    particle: "#67e8f9",
  },
  light: {
    label: "#334155",
    labelStrong: "#0b1020",
    ring: "rgba(255,255,255,0.95)",
    link: "rgba(71,85,105,0.2)",
    linkFocus: "rgba(124,58,237,0.75)",
    particle: "#0891b2",
  },
};

/** Lightweight canvas renderer for phones, low-power devices and reduced-motion users. */
export default function Graph2D({ data, width, height, onNodeClick }: Props) {
  const fgRef = useRef<ForceGraphMethods<GraphNode, GraphLink> | undefined>(undefined);
  const focus = useGraphFocus(data);
  const theme = useTheme();
  const ink = INK[theme];
  const fitted = useRef(false);
  const maxRank = useMemo(
    () => Math.max(...data.nodes.filter((n) => n.type !== "Person").map((n) => n.pagerank), 1e-6),
    [data],
  );

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge")?.strength?.(-70);
    const timers = [700, 2200].map((ms) =>
      window.setTimeout(() => !fitted.current && fg.zoomToFit(500, 12), ms),
    );
    const person = data.nodes.find((n) => n.type === "Person");
    if (person) {
      person.fx = 0;
      person.fy = 0;
    }
    return () => {
      for (const timer of timers) window.clearTimeout(timer);
    };
  }, [data]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const timer = window.setTimeout(() => {
      if (focus.active && focus.nodes.size) fg.zoomToFit(900, 40, (n) => focus.nodes.has(String(n.id)));
      else fg.zoomToFit(900, 24);
    }, 150);
    return () => window.clearTimeout(timer);
  }, [focus]);

  const paint = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const inFocus = !focus.active || focus.nodes.has(node.id);
      const emphasised = focus.emphasis.has(node.id);
      const r = nodeRadius(node, maxRank) * (emphasised ? 1.4 : 1) * 0.9;
      const color = nodeColor(node, theme);
      ctx.save();
      ctx.globalAlpha = inFocus ? 1 : 0.16;
      ctx.shadowColor = color;
      ctx.shadowBlur = emphasised ? 22 : inFocus ? (theme === "dark" ? 12 : 6) : 0;
      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.shadowBlur = 0;
      // A thin ring separates overlapping nodes from each other and from the links.
      ctx.lineWidth = Math.max(0.6 / scale, 0.25);
      ctx.strokeStyle = ink.ring;
      ctx.stroke();
      const showLabel = focus.active
        ? inFocus
        : isLandmark(node, maxRank) &&
          (node.type === "Person" || node.type === "Project" || node.type === "Role" || scale > 1.6);
      if (showLabel) {
        const fontSize = Math.max(10 / scale, 2.2);
        ctx.font = `${node.type === "Person" ? 600 : 500} ${fontSize}px Geist, Inter, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = emphasised ? ink.labelStrong : ink.label;
        const label = node.name.length > 28 ? `${node.name.slice(0, 26)}…` : node.name;
        ctx.fillText(label, node.x ?? 0, (node.y ?? 0) + r + 1.5);
      }
      ctx.restore();
    },
    [focus, maxRank, theme, ink],
  );

  return (
    <ForceGraph2D<GraphNode, GraphLink>
      ref={fgRef}
      width={width}
      height={height}
      graphData={data}
      backgroundColor="rgba(0,0,0,0)"
      cooldownTicks={180}
      onEngineStop={() => {
        if (!fitted.current) {
          fitted.current = true;
          fgRef.current?.zoomToFit(600, 16);
        }
      }}
      nodeRelSize={4}
      nodeCanvasObject={paint}
      nodePointerAreaPaint={(node, color, ctx) => {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(node.x ?? 0, node.y ?? 0, nodeRadius(node, maxRank) + 2, 0, Math.PI * 2);
        ctx.fill();
      }}
      linkColor={(link) => (focus.links.has(linkKey(link)) ? ink.linkFocus : ink.link)}
      linkWidth={(link) => (focus.links.has(linkKey(link)) ? 1.4 : 0.5)}
      linkDirectionalParticles={(link) => (focus.links.has(linkKey(link)) ? 2 : 0)}
      linkDirectionalParticleWidth={2.2}
      linkDirectionalParticleColor={() => ink.particle}
      onNodeClick={(node) => onNodeClick(node)}
    />
  );
}
