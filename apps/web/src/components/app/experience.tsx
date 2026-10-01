"use client";

import { MessagesSquare, ScanSearch } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useUI } from "@/lib/store";
import type { GraphData, Profile } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ChatPanel } from "../chat/chat-panel";
import { EntitySheet } from "../entity/entity-sheet";
import { FitPanel } from "../fit/fit-panel";
import { GraphCanvas } from "../graph/graph-canvas";
import { GraphOverlay } from "../graph/graph-overlay";
import { CommandMenu } from "../layout/command-menu";
import { Hero } from "../layout/hero";
import { TopBar } from "../layout/top-bar";

const FALLBACK_STARTERS = [
  "Give me a 30-second overview of Dorian.",
  "What has Dorian built with LLMs, RAG and AI agents?",
  "How strong is Dorian on Kubernetes and DevOps?",
  "Walk me through his experience at GoodBarber.",
];

export function Experience() {
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [graphError, setGraphError] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const tab = useUI((s) => s.tab);
  const setTab = useUI((s) => s.setTab);
  const selectedId = useUI((s) => s.selectedId);

  useEffect(() => {
    let cancelled = false;
    const load = (attempt = 0) => {
      api
        .graph()
        .then((data) => !cancelled && setGraph(data))
        .catch(() => {
          if (cancelled) return;
          setGraphError(true);
          if (attempt < 5) window.setTimeout(() => load(attempt + 1), 3000 * (attempt + 1));
        });
    };
    load();
    api
      .profile()
      .then((data) => !cancelled && setProfile(data))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const starters = profile?.starterQuestions?.length ? profile.starterQuestions : FALLBACK_STARTERS;
  const emptyGraph = graph !== null && graph.nodes.length === 0;

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopBar onSearch={() => setCommandOpen(true)} />
      <main className="relative flex min-h-0 flex-1 flex-col lg:block">
        <section
          className="relative h-[40vh] shrink-0 lg:absolute lg:inset-y-0 lg:right-[calc(min(460px,40vw)+1rem)] lg:left-0 lg:h-auto"
          aria-label="Knowledge graph"
        >
          <GraphCanvas data={graph} />
          {(graphError && !graph) || emptyGraph ? (
            <div className="absolute inset-0 grid place-items-center p-6 text-center text-sm text-fg-muted">
              <p>
                The knowledge graph is being built — the ingestion job runs right after each deployment.
                <br />
                Refresh in a minute.
              </p>
            </div>
          ) : null}
          <Hero profile={profile} />
          <GraphOverlay data={graph} />
        </section>

        <aside className="relative z-20 flex min-h-0 flex-1 flex-col lg:absolute lg:top-1 lg:right-4 lg:bottom-4 lg:w-[min(460px,40vw)]">
          <div className="glass flex min-h-0 flex-1 flex-col overflow-hidden border-x-0 border-b-0 lg:rounded-2xl lg:border">
            {selectedId && <EntitySheet id={selectedId} />}
            <div className={cn("flex min-h-0 flex-1 flex-col", selectedId && "hidden")}>
              <div role="tablist" aria-label="Mode" className="flex gap-1 border-b border-tint/[0.06] p-2">
                {[
                  { id: "ask" as const, label: "Ask the graph", icon: MessagesSquare },
                  { id: "fit" as const, label: "Job fit analyzer", icon: ScanSearch },
                ].map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    role="tab"
                    aria-selected={tab === item.id}
                    onClick={() => setTab(item.id)}
                    className={cn(
                      "flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm transition",
                      tab === item.id
                        ? "bg-tint/[0.08] text-fg shadow-[inset_0_1px_0_rgb(255_255_255/0.06)]"
                        : "text-fg-muted hover:text-fg",
                    )}
                  >
                    <item.icon className="size-4" />
                    {item.label}
                  </button>
                ))}
              </div>
              {/* Both panels stay mounted so the conversation survives tab switches. */}
              <div className={cn("min-h-0 flex-1", tab !== "ask" && "hidden")}>
                <ChatPanel starters={starters} featured={profile?.featuredProjects ?? []} />
              </div>
              <div className={cn("min-h-0 flex-1", tab !== "fit" && "hidden")}>
                <FitPanel />
              </div>
            </div>
          </div>
        </aside>
      </main>
      <CommandMenu open={commandOpen} onOpenChange={setCommandOpen} starters={starters} />
    </div>
  );
}
