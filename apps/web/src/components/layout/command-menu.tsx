"use client";

import { Command } from "cmdk";
import { Box, Download, MessageSquareText, Orbit, ScanSearch, Waypoints } from "lucide-react";
import { useRouter } from "next/navigation";
import { Dialog } from "radix-ui";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { nodeColor } from "@/lib/graph-style";
import { useUI } from "@/lib/store";
import { useTheme } from "@/lib/theme";
import type { NodeType } from "@/lib/types";
import { Dot } from "../ui/badge";

export function CommandMenu({
  open,
  onOpenChange,
  starters,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  starters: string[];
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ id: string; name: string; type: string }[]>([]);
  const select = useUI((s) => s.select);
  const ask = useUI((s) => s.ask);
  const setTab = useUI((s) => s.setTab);
  const mode = useUI((s) => s.mode);
  const setMode = useUI((s) => s.setMode);
  const router = useRouter();
  const theme = useTheme();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    const timer = window.setTimeout(() => {
      api
        .search(query.trim())
        .then((r) => setResults(r.results))
        .catch(() => setResults([]));
    }, 120);
    return () => window.clearTimeout(timer);
  }, [query]);

  const run = (fn: () => void) => {
    fn();
    onOpenChange(false);
    setQuery("");
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-slate-900/20 backdrop-blur-sm dark:bg-black/50" />
        <Dialog.Content className="glass fixed top-[16vh] left-1/2 z-50 w-[min(640px,calc(100vw-24px))] -translate-x-1/2 overflow-hidden rounded-2xl">
          <Dialog.Title className="sr-only">Search the career graph</Dialog.Title>
          <Command shouldFilter={false} label="Search the career graph">
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder="Search skills, projects, roles… or type a question"
              className="w-full border-b border-tint/[0.07] bg-transparent px-4 py-3.5 text-sm text-fg placeholder:text-fg-subtle focus:outline-none"
            />
            <Command.List className="max-h-[52vh] overflow-y-auto p-2 scrollbar-thin">
              <Command.Empty className="px-3 py-6 text-center text-sm text-fg-subtle">
                No entity found.
              </Command.Empty>
              {query.trim().length > 3 && (
                <Command.Group
                  heading="Ask"
                  className="px-1 text-[11px] text-fg-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
                >
                  <Item
                    icon={<MessageSquareText className="size-4 text-violet-600 dark:text-violet-300" />}
                    onSelect={() => run(() => ask(query.trim()))}
                  >
                    Ask “{query.trim()}”
                  </Item>
                </Command.Group>
              )}
              {results.length > 0 && (
                <Command.Group
                  heading="Entities"
                  className="px-1 text-[11px] text-fg-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
                >
                  {results.map((r) => (
                    <Item
                      key={r.id}
                      icon={<Dot color={nodeColor({ type: r.type as NodeType, name: r.name }, theme)} />}
                      onSelect={() => run(() => select(r.id))}
                      hint={r.type}
                    >
                      {r.name}
                    </Item>
                  ))}
                </Command.Group>
              )}
              {!query && (
                <>
                  <Command.Group
                    heading="Suggested questions"
                    className="px-1 text-[11px] text-fg-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
                  >
                    {starters.slice(0, 4).map((q) => (
                      <Item
                        key={q}
                        icon={<MessageSquareText className="size-4 text-violet-600 dark:text-violet-300" />}
                        onSelect={() => run(() => ask(q))}
                      >
                        {q}
                      </Item>
                    ))}
                  </Command.Group>
                  <Command.Group
                    heading="Actions"
                    className="px-1 text-[11px] text-fg-subtle [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
                  >
                    <Item icon={<ScanSearch className="size-4" />} onSelect={() => run(() => setTab("fit"))}>
                      Analyze a job description
                    </Item>
                    <Item
                      icon={mode === "3d" ? <Box className="size-4" /> : <Orbit className="size-4" />}
                      onSelect={() => run(() => setMode(mode === "3d" ? "2d" : "3d"))}
                    >
                      Switch to {mode === "3d" ? "2D" : "3D"} graph
                    </Item>
                    <Item
                      icon={<Waypoints className="size-4" />}
                      onSelect={() => run(() => router.push("/how-it-works"))}
                    >
                      How this GraphRAG works
                    </Item>
                    <Item
                      icon={<Download className="size-4" />}
                      onSelect={() => run(() => window.open("/dorian-lovichi-resume.pdf", "_blank"))}
                    >
                      Download résumé (PDF)
                    </Item>
                  </Command.Group>
                </>
              )}
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Item({
  children,
  icon,
  hint,
  onSelect,
}: {
  children: React.ReactNode;
  icon: React.ReactNode;
  hint?: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm text-fg-soft data-[selected=true]:bg-tint/[0.07] data-[selected=true]:text-fg"
    >
      <span className="grid size-5 place-items-center text-fg-muted">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {hint && <span className="text-[10px] uppercase tracking-wider text-fg-subtle">{hint}</span>}
    </Command.Item>
  );
}
