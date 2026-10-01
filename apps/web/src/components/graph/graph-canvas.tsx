"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { useUI } from "@/lib/store";
import type { GraphData, GraphNode } from "@/lib/types";

// WebGL/canvas libraries touch `window` at import time: client-only, code-split.
const Graph3D = dynamic(() => import("./graph-3d"), { ssr: false, loading: () => <GraphSkeleton /> });
const Graph2D = dynamic(() => import("./graph-2d"), { ssr: false, loading: () => <GraphSkeleton /> });

function GraphSkeleton() {
  return (
    <div className="absolute inset-0 grid place-items-center">
      <div className="flex items-center gap-3 text-sm text-fg-muted">
        <span className="size-2 animate-ping rounded-full bg-violet-400" />
        Loading the knowledge graph…
      </div>
    </div>
  );
}

function webglAvailable() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export function GraphCanvas({ data }: { data: GraphData | null }) {
  const container = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const mode = useUI((s) => s.mode);
  const setMode = useUI((s) => s.setMode);
  const select = useUI((s) => s.select);
  const hiddenTypes = useUI((s) => s.hiddenTypes);

  useEffect(() => {
    const small = window.matchMedia("(max-width: 768px)").matches;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (small || reduced || !webglAvailable()) setMode("2d");
  }, [setMode]);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const visible = useVisibleGraph(data, hiddenTypes);
  const onNodeClick = (node: GraphNode) => select(node.id);

  return (
    // `isolate`: the label renderer gives each label a z-index; keep them below panels and dialogs.
    <div
      ref={container}
      className="absolute inset-0 isolate"
      role="img"
      aria-label="Interactive knowledge graph of Dorian's career"
    >
      {!visible || size.width === 0 ? (
        <GraphSkeleton />
      ) : mode === "3d" ? (
        <Graph3D data={visible} width={size.width} height={size.height} onNodeClick={onNodeClick} />
      ) : (
        <Graph2D data={visible} width={size.width} height={size.height} onNodeClick={onNodeClick} />
      )}
    </div>
  );
}

function useVisibleGraph(data: GraphData | null, hiddenTypes: string[]): GraphData | null {
  const [visible, setVisible] = useState<GraphData | null>(null);
  useEffect(() => {
    if (!data) return;
    if (hiddenTypes.length === 0) {
      setVisible(data);
      return;
    }
    const nodes = data.nodes.filter((n) => !hiddenTypes.includes(n.type));
    const ids = new Set(nodes.map((n) => n.id));
    const endpoint = (v: unknown) => (typeof v === "object" && v ? (v as GraphNode).id : String(v));
    const links = data.links.filter((l) => ids.has(endpoint(l.source)) && ids.has(endpoint(l.target)));
    setVisible({ version: data.version, nodes, links });
  }, [data, hiddenTypes]);
  return visible;
}
