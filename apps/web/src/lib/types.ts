export type NodeType =
  | "Person"
  | "Role"
  | "Organization"
  | "Project"
  | "Skill"
  | "Domain"
  | "Degree"
  | "Language"
  | "Award"
  | "Location";

export interface GraphNode {
  id: string;
  name: string;
  type: NodeType;
  pagerank: number;
  degree: number;
  community: string | null;
  category?: string;
  domain?: string;
  featured?: boolean;
  minor?: boolean;
  period?: string;
  strength?: number;
  // runtime fields added by the force simulation
  x?: number;
  y?: number;
  z?: number;
  fx?: number;
  fy?: number;
  fz?: number;
}

export interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  type: string;
}

export interface GraphData {
  version: string;
  nodes: GraphNode[];
  links: GraphLink[];
}

/** Evidence subgraph streamed by the agent (`data-graph` parts). */
export interface GraphHighlight {
  nodes: string[];
  links: { source: string; target: string; type: string }[];
  seeds: string[];
  emphasis: string[];
}

export interface SourceRef {
  ref: number;
  kind: "passage" | "entity" | "community";
  id: string;
  title: string;
  snippet: string;
  url: string | null;
  docKind: string | null;
  entityIds: string[];
  cited: boolean;
}

export interface MessageMetadata {
  model?: string | null;
  plannerModel?: string | null;
  latencyMs?: number;
  retrievalMs?: number;
  degraded?: boolean;
  cached?: boolean;
  graphVersion?: string;
}

export type FitStatus = "strong" | "partial" | "transferable" | "gap";

export interface FitRequirement {
  requirement: string;
  category: string;
  importance: "must" | "nice";
  status: FitStatus;
  rationale: string;
  evidence: number[];
}

export interface FitReportData {
  job: { title: string; company: string | null; seniority: string | null; location: string | null };
  score: { percent: number; counts: Record<FitStatus, number>; mustHaveGaps: number };
  headline: string;
  summary: string;
  strengths: string[];
  gaps: string[];
  requirements: FitRequirement[];
  interviewQuestions: string[];
  sources: SourceRef[];
}

export interface EntityDetails {
  entity: {
    id: string;
    type: NodeType;
    name: string;
    description?: string;
    url?: string;
    aliases?: string[];
    highlights?: string[];
    category?: string;
    period?: string;
    start?: string;
    end?: string;
    repo_url?: string;
    languages?: string[];
    strength?: number;
    evidence?: number;
    last_used?: string;
    [key: string]: unknown;
  };
  relations: Record<string, { id: string; name: string; type: NodeType; props?: Record<string, unknown> }[]>;
  evidence: {
    id: string;
    title: string;
    text: string;
    doc_title: string;
    url: string | null;
    kind: string;
  }[];
}

export interface Profile {
  person: {
    name: string;
    headline?: string;
    location?: string;
    email?: string;
    linkedin?: string;
    github?: string;
    website?: string;
    description?: string;
    work_authorization?: string;
  } | null;
  topSkills: { id: string; name: string; category: string | null; strength: number; evidence: number }[];
  featuredProjects: { id: string; name: string; url: string | null; summary: string }[];
  starterQuestions: string[];
}

export interface Stats {
  graph: {
    version: string;
    builtAt: string | null;
    entities: number;
    relations: number;
    entitiesByType: Record<string, number>;
    relationsByType: Record<string, number>;
    documents: number | null;
    chunks: number | null;
    communities: number | null;
    repositories: number | null;
    ingestionSeconds: number | null;
  };
  models: { chat: string[]; fast: string[]; extraction: string[]; embedding: string };
  llm: { enabled: boolean; budget_remaining: number; open_circuits: Record<string, number> };
  cache: { hits: number; misses: number };
  neo4j: boolean;
}
