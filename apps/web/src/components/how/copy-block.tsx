"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

export function CopyBlock({ label, code }: { label: string; code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div data-theme="dark" className="overflow-hidden rounded-2xl border border-tint/[0.08] bg-ink-900">
      <div className="flex items-center justify-between border-b border-tint/[0.06] px-4 py-2 text-[11px] text-fg-subtle">
        {label}
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard.writeText(code).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1600);
            });
          }}
          className="inline-flex items-center gap-1 text-fg-muted hover:text-fg"
        >
          {copied ? (
            <Check className="size-3.5 text-emerald-600 dark:text-emerald-300" />
          ) : (
            <Copy className="size-3.5" />
          )}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-xs leading-relaxed text-cyan-100/90 scrollbar-thin">
        {code}
      </pre>
    </div>
  );
}
