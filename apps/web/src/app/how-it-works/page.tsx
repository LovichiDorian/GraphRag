import {
  Boxes,
  Brain,
  Database,
  FileText,
  GitBranch,
  Layers,
  Network,
  Route,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Waypoints,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { CopyBlock } from "@/components/how/copy-block";
import { LiveStats } from "@/components/how/live-stats";
import { TopBar } from "@/components/layout/top-bar";
import { GithubIcon } from "@/components/ui/brand-icons";

export const metadata: Metadata = {
  title: "How it works",
  description:
    "Architecture of an agentic GraphRAG over a CV and GitHub: Gemini, Neo4j, FastAPI, Next.js, MCP, k3s and Argo CD.",
};

const PIPELINE = [
  {
    icon: FileText,
    title: "Schema-guided extraction",
    text: "Gemini structured output turns the résumé, READMEs and docs into typed entities (roles, projects, skills, domains) and relations — validated with Pydantic, cached by content hash.",
  },
  {
    icon: ShieldCheck,
    title: "Code-verified skills",
    text: "Every repository tarball is scanned in memory: package.json, requirements, Gradle, pubspec, Dockerfiles and Kubernetes manifests prove which technologies were really used.",
  },
  {
    icon: Waypoints,
    title: "Entity resolution",
    text: "A canonical ontology of 140+ technologies and 260+ aliases maps names (k8s → Kubernetes, React 19 → React); unknown names are merged by embedding similarity. Umbrella skills are inferred (LangGraph ⇒ AI agents).",
  },
  {
    icon: Layers,
    title: "Communities & reports",
    text: "Louvain community detection clusters the graph into themes; an LLM writes a recruiter-facing report for each — the GraphRAG “global search” layer.",
  },
  {
    icon: Route,
    title: "Planner agent",
    text: "A fast model rewrites the question, decomposes it into search queries, links entities against the catalog and, when counting or listing is needed, writes guarded read-only Cypher.",
  },
  {
    icon: Network,
    title: "Hybrid retrieval + PageRank",
    text: "Dense (Gemini embeddings, Neo4j vector index) and sparse (Lucene) hits are fused with Reciprocal Rank Fusion, then HippoRAG-style Personalized PageRank pulls in multi-hop evidence.",
  },
  {
    icon: Brain,
    title: "Grounded synthesis",
    text: "The synthesizer streams a cited answer over the Vercel AI SDK UI-message protocol, with model fallback chains, circuit breakers and seamless continuation if a model fails mid-answer.",
  },
  {
    icon: ScanSearch,
    title: "Honest job-fit",
    text: "Requirements are extracted from a job description, each gets its own evidence retrieval, an LLM grades them and the score is computed deterministically — gaps included.",
  },
];

const STACK = [
  ["AI", "Gemini 3.x (flash / flash-lite) · gemini-embedding-2 · structured output · MCP server"],
  ["Graph", "Neo4j 2026 · vector + full-text indexes · Cypher · Personalized PageRank · Louvain"],
  ["Backend", "Python 3.14 · FastAPI · async Neo4j driver · Pydantic · uv · Prometheus metrics"],
  ["Frontend", "Next.js 16 · React 19 · Tailwind CSS 4 · Vercel AI SDK · three.js + bloom · Motion"],
  ["Platform", "k3s · Argo CD (GitOps) · Traefik · cert-manager · NetworkPolicies · CronJobs"],
  [
    "Supply chain",
    "GitHub Actions · native arm64 + amd64 builds · SBOM + provenance · cosign keyless signing · Trivy",
  ],
];

function Box({ title, items, accent }: { title: string; items: string[]; accent: string }) {
  return (
    <div className="glass relative rounded-2xl p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">
        <span
          className="size-2 rounded-full"
          style={{ background: accent, boxShadow: `0 0 12px ${accent}` }}
        />
        {title}
      </div>
      <ul className="grid gap-1 text-xs text-fg-muted">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Arrow() {
  return (
    <div className="flex items-center justify-center py-1 text-fg-faint lg:py-0">
      <svg width="40" height="16" viewBox="0 0 40 16" className="rotate-90 lg:rotate-0" aria-hidden="true">
        <defs>
          <linearGradient id="arrow-gradient" x1="0" x2="1">
            <stop offset="0" stopColor="#8b5cf6" />
            <stop offset="1" stopColor="#22d3ee" />
          </linearGradient>
        </defs>
        <path d="M2 8h32" stroke="url(#arrow-gradient)" strokeWidth="2" strokeDasharray="4 4">
          <animate attributeName="stroke-dashoffset" from="16" to="0" dur="1s" repeatCount="indefinite" />
        </path>
        <path d="M30 3l6 5-6 5" fill="none" stroke="#22d3ee" strokeWidth="2" />
      </svg>
    </div>
  );
}

export default function HowItWorks() {
  return (
    <div className="min-h-dvh">
      <TopBar />
      <main className="mx-auto max-w-6xl px-4 pt-10 pb-24 sm:px-6">
        <section className="max-w-3xl">
          <p className="mb-3 inline-flex items-center gap-2 rounded-full border border-tint/10 bg-tint/[0.04] px-3 py-1 text-xs text-fg-soft">
            <Sparkles className="size-3.5 text-violet-600 dark:text-violet-300" /> Architecture
          </p>
          <h1 className="text-4xl font-semibold tracking-tight text-fg sm:text-5xl">
            An agentic <span className="text-gradient">GraphRAG</span>, end to end.
          </h1>
          <p className="mt-4 text-[15px] leading-relaxed text-fg-muted">
            This site turns a résumé and a GitHub account into a Neo4j knowledge graph, then lets anyone
            question it in natural language. Answers are grounded, cited, and the evidence subgraph lights up
            in 3D. Everything below is open source and runs on a single-node k3s cluster managed with GitOps.
          </p>
        </section>

        <section className="mt-12" aria-label="Architecture diagram">
          <div className="grid items-stretch gap-2 lg:grid-cols-[1fr_auto_1.15fr_auto_1fr_auto_1fr]">
            <Box
              title="Sources"
              accent="#f472b6"
              items={["profile.yaml (the CV)", "GitHub repositories", "Markdown notes"]}
            />
            <Arrow />
            <Box
              title="Ingestion job"
              accent="#a78bfa"
              items={[
                "LLM extraction (Gemini)",
                "Manifest analysis",
                "Entity resolution",
                "Communities + reports",
                "Embeddings (768-d)",
              ]}
            />
            <Arrow />
            <Box
              title="Neo4j"
              accent="#22d3ee"
              items={["Property graph", "Vector indexes", "Full-text indexes", "Answer cache"]}
            />
            <Arrow />
            <Box
              title="FastAPI agents"
              accent="#34d399"
              items={["Planner → Retriever → Synthesizer", "Job-fit analyzer", "MCP server", "SSE streaming"]}
            />
          </div>
        </section>

        <section className="mt-16">
          <h2 className="mb-5 text-xl font-semibold text-fg">The pipeline</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {PIPELINE.map((step, i) => (
              <div key={step.title} className="glass-soft rounded-2xl p-4">
                <div className="mb-3 flex items-center justify-between">
                  <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-violet-500/30 to-cyan-500/20 text-violet-700 dark:text-violet-200">
                    <step.icon className="size-4" />
                  </span>
                  <span className="font-mono text-[11px] text-fg-faint">0{i + 1}</span>
                </div>
                <h3 className="text-sm font-semibold text-fg">{step.title}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-fg-muted">{step.text}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-16 grid gap-6 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <h2 className="mb-5 text-xl font-semibold text-fg">Live graph statistics</h2>
            <LiveStats />
          </div>
          <div>
            <h2 className="mb-5 text-xl font-semibold text-fg">Stack</h2>
            <dl className="glass-soft divide-y divide-tint/[0.06] rounded-2xl">
              {STACK.map(([label, value]) => (
                <div key={label} className="grid grid-cols-[110px_1fr] gap-3 px-4 py-3 text-sm">
                  <dt className="text-fg-subtle">{label}</dt>
                  <dd className="text-fg-soft">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section className="mt-16">
          <h2 className="mb-2 text-xl font-semibold text-fg">Deployment: GitOps on k3s</h2>
          <p className="mb-5 max-w-3xl text-sm leading-relaxed text-fg-muted">
            A push to <code className="text-fg-soft">main</code> runs lint, type checks and tests, builds
            multi-arch images on native amd64 and arm64 runners, attaches an SBOM and provenance, signs them
            with cosign, and commits the new tags. Argo CD notices the commit, rolls the deployments, and
            re-runs the ingestion job as a PostSync hook; a nightly CronJob picks up new GitHub activity.
          </p>
          <div className="grid gap-3 md:grid-cols-4">
            {[
              {
                icon: GitBranch,
                title: "GitHub Actions",
                text: "CI · multi-arch build · SBOM · cosign · tag bump",
              },
              {
                icon: Boxes,
                title: "Argo CD",
                text: "Auto-sync, self-heal, prune · PostSync ingestion hook",
              },
              {
                icon: ShieldCheck,
                title: "Traefik + cert-manager",
                text: "TLS, rate limiting, security headers",
              },
              {
                icon: Database,
                title: "Neo4j StatefulSet",
                text: "Persistent volume · NetworkPolicy-isolated",
              },
            ].map((item) => (
              <div key={item.title} className="glass-soft rounded-2xl p-4">
                <item.icon className="mb-2 size-5 text-cyan-700 dark:text-cyan-300" />
                <div className="text-sm font-semibold text-fg">{item.title}</div>
                <div className="mt-1 text-xs text-fg-muted">{item.text}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-16 grid gap-6 lg:grid-cols-2">
          <div>
            <h2 className="mb-2 text-xl font-semibold text-fg">Plug this graph into your AI assistant</h2>
            <p className="mb-4 text-sm leading-relaxed text-fg-muted">
              The API exposes a public <b className="text-fg-soft">Model Context Protocol</b> server. Add it
              to Claude, Cursor or any MCP client and ask your own assistant about Dorian — it gets tools like{" "}
              <code className="text-fg-soft">ask</code>, <code className="text-fg-soft">search_graph</code>{" "}
              and <code className="text-fg-soft">assess_job_fit</code>.
            </p>
            <CopyBlock
              label="Claude Code"
              code="claude mcp add --transport http dorian https://graphrag.dorianlovichi.com/mcp"
            />
          </div>
          <div className="lg:pt-9">
            <CopyBlock
              label="mcp.json (Cursor, Claude Desktop, VS Code…)"
              code={`{
  "mcpServers": {
    "dorian-career-graph": {
      "type": "http",
      "url": "https://graphrag.dorianlovichi.com/mcp"
    }
  }
}`}
            />
          </div>
        </section>

        <footer className="mt-20 flex flex-wrap items-center justify-between gap-4 border-t border-tint/[0.06] pt-6 text-sm text-fg-subtle">
          <span>Built by Dorian Lovichi · dorian@dorianlovichi.com</span>
          <div className="flex gap-4">
            <Link href="/" className="hover:text-fg">
              Explore the graph
            </Link>
            <a
              href="https://github.com/LovichiDorian/GraphRag"
              className="inline-flex items-center gap-1.5 hover:text-fg"
            >
              <GithubIcon className="size-4" /> Source code
            </a>
          </div>
        </footer>
      </main>
    </div>
  );
}
