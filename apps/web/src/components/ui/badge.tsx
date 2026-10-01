import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export function Badge({ className, style, ...props }: ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-tint/10 bg-tint/[0.04] px-1.5 py-0.5 text-[11px] font-medium text-fg-soft",
        className,
      )}
      style={style}
      {...props}
    />
  );
}

export function Dot({ color, className }: { color: string; className?: string }) {
  return (
    <span
      className={cn("inline-block size-2 shrink-0 rounded-full", className)}
      style={{ background: color, boxShadow: `0 0 10px ${color}` }}
    />
  );
}

export function Kbd({ className, ...props }: ComponentProps<"kbd">) {
  return (
    <kbd
      className={cn(
        "rounded border border-tint/10 bg-tint/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-fg-muted",
        className,
      )}
      {...props}
    />
  );
}
