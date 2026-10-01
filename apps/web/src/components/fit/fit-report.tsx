"use client";

import { CircleAlert, MessageCircleQuestion, ThumbsUp } from "lucide-react";
import { motion } from "motion/react";
import { useUI } from "@/lib/store";
import type { FitReportData, FitStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Markdown } from "../chat/markdown";

const STATUS: Record<FitStatus, { label: string; className: string; bar: string }> = {
  strong: {
    label: "Strong",
    className: "border-emerald-400/30 bg-emerald-400/10 text-emerald-700 dark:text-emerald-200",
    bar: "bg-emerald-400",
  },
  partial: {
    label: "Partial",
    className: "border-sky-400/30 bg-sky-400/10 text-sky-700 dark:text-sky-200",
    bar: "bg-sky-400",
  },
  transferable: {
    label: "Transferable",
    className: "border-violet-400/30 bg-violet-400/10 text-violet-700 dark:text-violet-200",
    bar: "bg-violet-400",
  },
  gap: {
    label: "Gap",
    className: "border-amber-400/30 bg-amber-400/10 text-amber-800 dark:text-amber-200",
    bar: "bg-amber-400",
  },
};

function ScoreRing({ percent }: { percent: number }) {
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  return (
    <div className="relative size-28 shrink-0">
      <svg viewBox="0 0 100 100" className="size-full -rotate-90">
        <defs>
          <linearGradient id="fit-ring" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#8b5cf6" />
            <stop offset="100%" stopColor="#22d3ee" />
          </linearGradient>
        </defs>
        <circle cx="50" cy="50" r={radius} className="stroke-tint/[0.08]" strokeWidth="8" fill="none" />
        <motion.circle
          cx="50"
          cy="50"
          r={radius}
          stroke="url(#fit-ring)"
          strokeWidth="8"
          strokeLinecap="round"
          fill="none"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - percent / 100) }}
          transition={{ duration: 1.2, ease: "easeOut" }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <div className="text-3xl font-semibold tracking-tight text-fg">{percent}</div>
          <div className="text-[10px] uppercase tracking-wider text-fg-muted">fit score</div>
        </div>
      </div>
    </div>
  );
}

export function FitReport({ report }: { report: FitReportData }) {
  const setHighlight = useUI((s) => s.setHighlight);
  const { score } = report;
  const byRef = new Map(report.sources.map((s) => [s.ref, s]));
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-4">
        <ScoreRing percent={score.percent} />
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wider text-fg-subtle">
            {report.job.title}
            {report.job.company ? ` · ${report.job.company}` : ""}
          </div>
          <h2 className="mt-1 text-base font-semibold leading-snug text-fg">{report.headline}</h2>
          <div className="mt-2 flex flex-wrap gap-1">
            {(Object.keys(STATUS) as FitStatus[]).map((status) =>
              score.counts[status] ? (
                <span
                  key={status}
                  className={cn("rounded-md border px-1.5 py-0.5 text-[10px]", STATUS[status].className)}
                >
                  {score.counts[status]} {STATUS[status].label.toLowerCase()}
                </span>
              ) : null,
            )}
          </div>
        </div>
      </div>

      <Markdown text={report.summary} sources={report.sources} />

      <section>
        <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-fg-subtle">Requirements</h3>
        <div className="grid gap-2">
          {report.requirements.map((item, i) => (
            <motion.div
              key={item.requirement}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.04 * i }}
              className="rounded-xl border border-tint/[0.06] bg-tint/[0.02] p-3 transition hover:border-tint/15"
              onMouseEnter={() => {
                const ids = item.evidence.flatMap((n) => byRef.get(n)?.entityIds ?? []);
                if (ids.length) setHighlight({ nodes: ids, links: [], seeds: [], emphasis: ids });
              }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="text-sm text-fg">
                  {item.requirement}
                  {item.importance === "must" && (
                    <span className="ml-1.5 text-[10px] text-fg-subtle">must-have</span>
                  )}
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-medium",
                    STATUS[item.status].className,
                  )}
                >
                  {STATUS[item.status].label}
                </span>
              </div>
              <div className="mt-1.5 text-xs leading-relaxed text-fg-muted">
                <Markdown text={item.rationale} sources={report.sources} />
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      <section className="grid gap-3">
        <List
          icon={<ThumbsUp className="size-3.5 text-emerald-600 dark:text-emerald-300" />}
          title="Why Dorian"
          items={report.strengths}
          report={report}
        />
        <List
          icon={<CircleAlert className="size-3.5 text-amber-700 dark:text-amber-300" />}
          title="Honest gaps"
          items={report.gaps}
          report={report}
        />
        <List
          icon={<MessageCircleQuestion className="size-3.5 text-violet-600 dark:text-violet-300" />}
          title="Questions to ask in the interview"
          items={report.interviewQuestions}
          report={report}
        />
      </section>
    </div>
  );
}

function List({
  icon,
  title,
  items,
  report,
}: {
  icon: React.ReactNode;
  title: string;
  items: string[];
  report: FitReportData;
}) {
  if (!items.length) return null;
  return (
    <div className="rounded-xl border border-tint/[0.06] bg-tint/[0.02] p-3">
      <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-fg-soft">
        {icon} {title}
      </h3>
      <ul className="grid gap-1 text-xs leading-relaxed text-fg-muted">
        {items.map((item) => (
          <li key={item}>
            <Markdown text={`- ${item}`} sources={report.sources} />
          </li>
        ))}
      </ul>
    </div>
  );
}
