"use client";

import { MapPin } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useUI } from "@/lib/store";
import type { Profile } from "@/lib/types";

export function Hero({ profile }: { profile: Profile | null }) {
  const highlight = useUI((s) => s.highlight);
  const selected = useUI((s) => s.selectedId);
  const visible = !highlight && !selected;
  const person = profile?.person;
  const skills = profile?.topSkills.slice(0, 7) ?? [];

  return (
    <AnimatePresence>
      {visible && (
        <motion.section
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.5 }}
          className="pointer-events-none absolute top-0 left-0 z-10 hidden max-w-2xl hero-fade pt-4 pr-24 pb-16 pl-6 lg:block"
        >
          <p className="mb-3 inline-flex items-center gap-2 rounded-full border border-tint/10 bg-tint/[0.04] px-3 py-1 text-xs text-fg-soft backdrop-blur">
            <span className="size-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]" />
            {person?.headline ?? "Full-Stack Software Engineer · Applied AI & DevOps"}
          </p>
          <h1 className="text-5xl leading-[1.05] font-semibold tracking-tight text-fg xl:text-6xl">
            Don&apos;t read my CV.
            <br />
            <span className="text-gradient">Query it.</span>
          </h1>
          <p className="mt-4 max-w-md text-[15px] leading-relaxed text-fg-muted">
            Every node is a role, project or skill extracted from my résumé and GitHub by an agentic GraphRAG
            pipeline. Ask a question — the evidence lights up.
          </p>
          {person?.location && (
            <p className="mt-3 flex items-center gap-1.5 text-xs text-fg-subtle">
              <MapPin className="size-3.5" /> {person.location}
            </p>
          )}
          {skills.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-1.5">
              {skills.map((skill) => (
                <span
                  key={skill.id}
                  className="rounded-full border border-tint/[0.08] bg-tint/[0.03] px-2.5 py-1 text-[11px] text-fg-soft backdrop-blur"
                >
                  {skill.name}
                </span>
              ))}
            </div>
          )}
        </motion.section>
      )}
    </AnimatePresence>
  );
}
