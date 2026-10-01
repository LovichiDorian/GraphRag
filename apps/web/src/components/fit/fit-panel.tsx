"use client";

import { Check, ClipboardPaste, LoaderCircle, RotateCcw, ScanSearch } from "lucide-react";
import { motion } from "motion/react";
import { useRef, useState } from "react";
import { errorMessage, readUIStream } from "@/lib/sse";
import { useUI } from "@/lib/store";
import type { FitReportData, GraphHighlight } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "../ui/button";
import { FitReport } from "./fit-report";

const SAMPLE_JD = `Full-Stack AI Engineer — San Diego, CA (hybrid)

We build LLM-powered products. You will design RAG pipelines and AI agents, ship React/TypeScript frontends and Python (FastAPI) services, and own deployments on Kubernetes.

Requirements
- 3+ years of professional software engineering experience
- Strong Python and TypeScript, React
- Hands-on experience with RAG, vector search and LLM agents (LangChain/LangGraph or similar)
- Docker, Kubernetes, CI/CD (GitHub Actions)
- PostgreSQL
- Nice to have: knowledge graphs, AWS, mobile development
- Fluent English; French is a plus`;

type Step = { id: string; title: string; done: boolean; detail?: string };

export function FitPanel() {
  const setHighlight = useUI((s) => s.setHighlight);
  const [jd, setJd] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [report, setReport] = useState<FitReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const run = async () => {
    if (jd.trim().length < 80 || running) return;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setRunning(true);
    setError(null);
    setReport(null);
    setSteps([]);
    try {
      const response = await fetch("/api/fit", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ jobDescription: jd }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      for await (const chunk of readUIStream(response)) {
        if (chunk.type === "tool-input-available") {
          setSteps((s) => [
            ...s,
            { id: String(chunk.toolCallId), title: String(chunk.title ?? chunk.toolName), done: false },
          ]);
        } else if (chunk.type === "tool-output-available") {
          const output = (chunk.output ?? {}) as Record<string, unknown>;
          const detail =
            chunk.toolCallId === "extract"
              ? `${(output.requirements as string[] | undefined)?.length ?? 0} requirements found`
              : chunk.toolCallId === "evidence"
                ? `${output.sources} pieces of evidence · ${output.entities} entities`
                : undefined;
          setSteps((s) =>
            s.map((step) => (step.id === chunk.toolCallId ? { ...step, done: true, detail } : step)),
          );
        } else if (chunk.type === "data-graph") {
          setHighlight(chunk.data as GraphHighlight);
        } else if (chunk.type === "data-fit") {
          setReport(chunk.data as FitReportData);
        } else if (chunk.type === "error") {
          throw new Error(String(chunk.errorText));
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  };

  if (report) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto p-4 scrollbar-thin">
          <FitReport report={report} />
        </div>
        <div className="border-t border-tint/[0.06] p-3">
          <Button
            variant="outline"
            className="w-full"
            onClick={() => {
              setReport(null);
              setSteps([]);
              setHighlight(null);
            }}
          >
            <RotateCcw /> Analyze another job
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-4 scrollbar-thin">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-fg">Is Dorian a fit for your role?</h2>
        <p className="mt-1 text-sm leading-relaxed text-fg-muted">
          Paste a job description. Agents extract its requirements, gather evidence for each one from the
          graph, and grade them honestly — the score is computed, not hallucinated.
        </p>
      </div>
      <div className="relative">
        <textarea
          value={jd}
          onChange={(e) => setJd(e.target.value)}
          placeholder="Paste the job description here…"
          aria-label="Job description"
          rows={11}
          maxLength={40000}
          className="block w-full resize-none rounded-xl border border-tint/10 bg-well p-3.5 text-sm leading-relaxed text-fg placeholder:text-fg-subtle focus:border-violet-400/50 focus:outline-none"
        />
        {!jd && (
          <button
            type="button"
            onClick={() => setJd(SAMPLE_JD)}
            className="absolute right-3 bottom-3 inline-flex items-center gap-1.5 rounded-lg border border-tint/10 bg-tint/[0.05] px-2.5 py-1.5 text-xs text-fg-soft hover:text-fg"
          >
            <ClipboardPaste className="size-3.5" /> Use a sample job
          </button>
        )}
      </div>
      <Button
        variant="primary"
        size="lg"
        disabled={jd.trim().length < 80 || running}
        onClick={() => void run()}
      >
        {running ? <LoaderCircle className="animate-spin" /> : <ScanSearch />}
        {running ? "Analyzing…" : "Analyze fit"}
      </Button>
      {jd.trim().length > 0 && jd.trim().length < 80 && (
        <p className="text-xs text-fg-subtle">Paste a bit more of the description (80+ characters).</p>
      )}
      {steps.length > 0 && (
        <ol className="grid gap-2 rounded-xl border border-tint/[0.06] bg-tint/[0.02] p-3 text-xs">
          {steps.map((step) => (
            <motion.li
              key={step.id}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex items-start gap-2"
            >
              {step.done ? (
                <Check className="mt-px size-3.5 text-emerald-600 dark:text-emerald-300" />
              ) : (
                <LoaderCircle className="mt-px size-3.5 animate-spin text-violet-600 dark:text-violet-300" />
              )}
              <div>
                <div className={cn(step.done ? "text-fg-soft" : "shimmer-text")}>{step.title}</div>
                {step.detail && <div className="text-fg-subtle">{step.detail}</div>}
              </div>
            </motion.li>
          ))}
        </ol>
      )}
      {error && (
        <div className="rounded-xl border border-amber-400/20 bg-amber-400/[0.06] px-3 py-2.5 text-xs text-amber-900 dark:text-amber-100">
          {error}
        </div>
      )}
    </div>
  );
}
