"use client";

import { useMemo } from "react";
import { useUI } from "@/lib/store";
import type { GraphData, GraphLink } from "@/lib/types";

export interface GraphFocus {
  active: boolean;
  nodes: Set<string>;
  links: Set<string>;
  emphasis: Set<string>;
}

const endpoint = (value: GraphLink["source"]) => (typeof value === "object" ? value.id : value);

export function linkKey(link: GraphLink): string {
  return `${endpoint(link.source)}->${endpoint(link.target)}`;
}

/** Derives the highlighted evidence subgraph (plus its connection to Dorian) from the UI store. */
export function useGraphFocus(data: GraphData): GraphFocus {
  const highlight = useUI((s) => s.highlight);
  return useMemo(() => {
    if (!highlight || highlight.nodes.length === 0) {
      return { active: false, nodes: new Set(), links: new Set(), emphasis: new Set() };
    }
    const nodes = new Set([...highlight.nodes, ...highlight.emphasis]);
    const links = new Set(highlight.links.map((l) => `${l.source}->${l.target}`));
    const person = data.nodes.find((n) => n.type === "Person");
    for (const link of data.links) {
      const source = endpoint(link.source);
      const target = endpoint(link.target);
      if (nodes.has(source) && nodes.has(target)) links.add(`${source}->${target}`);
      if (person && source === person.id && nodes.has(target) && link.type !== "HAS_SKILL") {
        links.add(`${source}->${target}`);
        nodes.add(source);
      }
    }
    return { active: true, nodes, links, emphasis: new Set(highlight.emphasis) };
  }, [highlight, data]);
}
