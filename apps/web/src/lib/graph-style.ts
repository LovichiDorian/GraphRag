import type { Theme } from "./theme-script";
import type { GraphNode, NodeType } from "./types";

type Palette = { types: Record<NodeType, string>; domains: Record<string, string> };

/** Pastel, glowing tones for the dark theme; deeper, saturated ones that read on white. */
export const PALETTES: Record<Theme, Palette> = {
  dark: {
    types: {
      Person: "#f8fafc",
      Role: "#a78bfa",
      Organization: "#60a5fa",
      Project: "#22d3ee",
      Skill: "#34d399",
      Domain: "#f472b6",
      Degree: "#818cf8",
      Language: "#2dd4bf",
      Award: "#facc15",
      Location: "#94a3b8",
    },
    // Skills are coloured by their CV domain, so clusters read at a glance.
    domains: {
      "Applied AI": "#e879f9",
      Frontend: "#38bdf8",
      Mobile: "#fb923c",
      "Backend & Data": "#34d399",
      "DevOps & Cloud": "#fbbf24",
      Languages: "#fb7185",
      Practices: "#94a3b8",
      "Domain expertise": "#a3e635",
    },
  },
  light: {
    types: {
      Person: "#1e1b4b",
      Role: "#7c3aed",
      Organization: "#2563eb",
      Project: "#0891b2",
      Skill: "#059669",
      Domain: "#db2777",
      Degree: "#4f46e5",
      Language: "#0d9488",
      Award: "#d97706",
      Location: "#64748b",
    },
    domains: {
      "Applied AI": "#c026d3",
      Frontend: "#0284c7",
      Mobile: "#ea580c",
      "Backend & Data": "#059669",
      "DevOps & Cloud": "#d97706",
      Languages: "#e11d48",
      Practices: "#64748b",
      "Domain expertise": "#65a30d",
    },
  },
};

const CATEGORY_DOMAIN: Record<string, string> = {
  ai: "Applied AI",
  devops: "DevOps & Cloud",
  cloud: "DevOps & Cloud",
  language: "Languages",
  database: "Backend & Data",
  practice: "Practices",
  "domain-knowledge": "Domain expertise",
};

export const TYPE_LABELS: Record<NodeType, string> = {
  Person: "Dorian",
  Role: "Roles",
  Organization: "Organizations",
  Project: "Projects",
  Skill: "Skills",
  Domain: "Domains",
  Degree: "Education",
  Language: "Languages",
  Award: "Awards",
  Location: "Places",
};

export function nodeColor(
  node: Pick<GraphNode, "type" | "category" | "name" | "domain">,
  theme: Theme = "light",
): string {
  const { types, domains } = PALETTES[theme];
  if (node.type === "Skill") {
    const domain = node.domain || (node.category ? CATEGORY_DOMAIN[node.category] : undefined);
    return (domain && domains[domain]) || types.Skill;
  }
  if (node.type === "Domain") return domains[node.name] ?? types.Domain;
  return types[node.type] ?? "#94a3b8";
}

export function nodeRadius(node: GraphNode, maxRank: number): number {
  if (node.type === "Person") return 9;
  const scaled = Math.sqrt(Math.max(node.pagerank, 0) / Math.max(maxRank, 1e-9));
  const base = node.type === "Skill" ? 1.6 : node.type === "Domain" ? 3.2 : 3;
  return base + scaled * 5.5;
}

/** Labels always shown (others appear on hover / when highlighted). */
export function isLandmark(node: GraphNode, maxRank: number): boolean {
  if (node.type === "Person" || node.type === "Domain" || node.type === "Role") return true;
  if (node.type === "Project")
    return Boolean(node.featured) || node.pagerank / Math.max(maxRank, 1e-9) > 0.55;
  return false;
}
