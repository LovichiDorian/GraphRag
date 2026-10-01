"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { ArrowUp, RotateCcw, Sparkles, Square } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/chat-types";
import { useUI } from "@/lib/store";
import { cn } from "@/lib/utils";
import { AssistantMessage } from "./message";

const MAX_CHARS = 1500;

function textOf(message: ChatMessage) {
  return message.parts.map((p) => (p.type === "text" ? p.text : "")).join("");
}

export function ChatPanel({ starters, featured = [] }: { starters: string[]; featured?: Featured[] }) {
  const setHighlight = useUI((s) => s.setHighlight);
  const pending = useUI((s) => s.pendingQuestion);
  const consumeQuestion = useUI((s) => s.consumeQuestion);
  const [input, setInput] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  const transport = useMemo(
    () =>
      new DefaultChatTransport<ChatMessage>({
        api: "/api/chat",
        // Send a compact, text-only history: the server rebuilds everything else.
        prepareSendMessagesRequest: ({ id, messages }) => ({
          body: {
            id,
            messages: messages.slice(-9).map((m) => ({ role: m.role, content: textOf(m).slice(0, 2000) })),
          },
        }),
      }),
    [],
  );

  const { messages, sendMessage, status, stop, error, regenerate, setMessages, clearError } =
    useChat<ChatMessage>({
      transport,
      experimental_throttle: 40,
      onData: (part) => {
        if (part.type === "data-graph") setHighlight(part.data);
      },
    });

  const busy = status === "submitted" || status === "streaming";

  const submit = (text: string) => {
    const question = text.trim().slice(0, MAX_CHARS);
    if (!question || busy) return;
    clearError();
    void sendMessage({ text: question });
    setInput("");
  };

  // Questions pushed from elsewhere (entity sheet, command menu, hero).
  // biome-ignore lint/correctness/useExhaustiveDependencies: fire only when a new question is queued
  useEffect(() => {
    if (pending && !busy) {
      const question = consumeQuestion();
      if (question) submit(question);
    }
  }, [pending, busy]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll on every new chunk
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
    if (nearBottom || status === "submitted") el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages, status]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-4 pt-4 pb-2 scrollbar-thin">
        {messages.length === 0 ? (
          <EmptyState starters={starters} featured={featured} onPick={submit} />
        ) : (
          <div className="flex flex-col gap-5">
            {messages.map((message, index) =>
              message.role === "user" ? (
                <motion.div
                  key={message.id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="ml-8 self-end rounded-2xl rounded-br-md border border-violet-400/20 bg-gradient-to-br from-violet-500/20 to-cyan-500/10 px-3.5 py-2 text-sm text-fg"
                >
                  {textOf(message)}
                </motion.div>
              ) : (
                <motion.div key={message.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <AssistantMessage
                    message={message}
                    streaming={busy && index === messages.length - 1}
                    isLast={index === messages.length - 1}
                    onFollowup={submit}
                  />
                </motion.div>
              ),
            )}
            {status === "submitted" && messages.at(-1)?.role === "user" && (
              <div className="flex items-center gap-2 text-xs text-fg-subtle">
                <Sparkles className="size-3.5 animate-pulse text-violet-600 dark:text-violet-300" />
                <span className="shimmer-text">Planning the graph search…</span>
              </div>
            )}
            {error && (
              <div className="rounded-xl border border-amber-400/20 bg-amber-400/[0.06] px-3 py-2.5 text-xs text-amber-900 dark:text-amber-100">
                {friendlyError(error.message)}
                <button
                  type="button"
                  onClick={() => void regenerate()}
                  className="ml-2 inline-flex items-center gap-1 text-amber-800 dark:text-amber-200 underline-offset-2 hover:underline"
                >
                  <RotateCcw className="size-3" /> Retry
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <form
        className="border-t border-tint/[0.06] p-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit(input);
        }}
      >
        <div className="relative rounded-xl border border-tint/10 bg-well transition focus-within:border-violet-400/50 focus-within:shadow-[0_0_0_4px_rgb(139_92_246/0.12)]">
          <textarea
            ref={textarea}
            value={input}
            maxLength={MAX_CHARS}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit(input);
              }
            }}
            rows={2}
            placeholder="Ask about skills, projects, experience… (any language)"
            aria-label="Ask a question about Dorian"
            className="block max-h-40 min-h-[3.25rem] w-full resize-none bg-transparent px-3.5 py-3 pr-12 text-sm text-fg placeholder:text-fg-subtle focus:outline-none"
          />
          {busy ? (
            <button
              type="button"
              onClick={() => void stop()}
              aria-label="Stop"
              className="absolute right-2 bottom-2 grid size-8 place-items-center rounded-lg bg-tint/10 text-fg hover:bg-tint/15"
            >
              <Square className="size-3.5 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              aria-label="Send"
              className="absolute right-2 bottom-2 grid size-8 place-items-center rounded-lg bg-gradient-to-br from-violet-500 to-cyan-500 text-white shadow-lg transition hover:brightness-110 disabled:opacity-30"
            >
              <ArrowUp className="size-4" />
            </button>
          )}
        </div>
        <div className="mt-2 flex items-center justify-between px-1 text-[10px] text-fg-subtle">
          <span>Grounded in a Neo4j knowledge graph · every claim is cited</span>
          {messages.length > 0 && !busy && (
            <button
              type="button"
              className="hover:text-fg-soft"
              onClick={() => {
                setMessages([]);
                setHighlight(null);
              }}
            >
              New chat
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

function friendlyError(message: string) {
  if (/429|too many/i.test(message))
    return "You're asking faster than my rate limit allows — wait a few seconds.";
  if (/budget/i.test(message))
    return "The daily AI budget of this demo is exhausted — please come back tomorrow.";
  return "The answer could not be completed. The AI model may be busy.";
}

type Featured = { id: string; name: string; url: string | null; summary: string };

function FeaturedWork({ items }: { items: Featured[] }) {
  const select = useUI((s) => s.select);
  if (!items.length) return null;
  return (
    <div>
      <div className="mb-2 text-[11px] font-medium uppercase tracking-wider text-fg-subtle">
        Featured work
      </div>
      <div className="grid gap-2">
        {items.slice(0, 3).map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => select(item.id)}
            className="group rounded-xl border border-tint/[0.06] bg-gradient-to-br from-tint/[0.04] to-transparent p-3 text-left transition hover:border-cyan-300/30"
          >
            <div className="text-sm font-medium text-fg group-hover:text-cyan-800 dark:group-hover:text-cyan-100">
              {item.name}
            </div>
            <div className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-fg-muted">{item.summary}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

function EmptyState({
  starters,
  featured,
  onPick,
}: {
  starters: string[];
  featured: Featured[];
  onPick: (q: string) => void;
}) {
  return (
    <div className="flex min-h-full flex-col justify-start gap-5 pb-2 lg:justify-end">
      <div className="order-last lg:order-first">
        <FeaturedWork items={featured} />
      </div>
      <div>
        <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-violet-400/20 bg-violet-500/10 px-2.5 py-1 text-[11px] text-violet-700 dark:text-violet-200">
          <span className="size-1.5 animate-pulse rounded-full bg-emerald-400" /> Agentic GraphRAG · live
        </div>
        <h2 className="text-lg font-semibold tracking-tight text-fg">Ask my career graph anything.</h2>
        <p className="mt-1 text-sm leading-relaxed text-fg-muted">
          A planner agent searches a knowledge graph built from my CV and GitHub, then answers with citations
          — and lights up the evidence in the graph.
        </p>
      </div>
      <div className="grid gap-2">
        {starters.map((question, i) => (
          <motion.button
            key={question}
            type="button"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 * i }}
            onClick={() => onPick(question)}
            className={cn(
              "group flex items-center gap-3 rounded-xl border border-tint/[0.07] bg-tint/[0.025] px-3.5 py-2.5 text-left text-sm text-fg-soft transition",
              "hover:border-violet-400/40 hover:bg-violet-500/[0.08] hover:text-fg",
            )}
          >
            <Sparkles className="size-3.5 shrink-0 text-violet-600/70 dark:text-violet-300/70 transition group-hover:text-cyan-700 dark:group-hover:text-cyan-300" />
            {question}
          </motion.button>
        ))}
      </div>
    </div>
  );
}
