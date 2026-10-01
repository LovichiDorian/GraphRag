"use client";

import { HoverCard as H } from "radix-ui";
import type { ReactNode } from "react";

export function HoverCard({ trigger, children }: { trigger: ReactNode; children: ReactNode }) {
  return (
    <H.Root openDelay={120} closeDelay={80}>
      <H.Trigger asChild>{trigger}</H.Trigger>
      <H.Portal>
        <H.Content
          side="top"
          sideOffset={8}
          collisionPadding={12}
          className="z-50 w-80 rounded-xl border border-tint/10 bg-popover/95 p-3 text-xs text-fg-soft shadow-2xl backdrop-blur-xl"
        >
          {children}
        </H.Content>
      </H.Portal>
    </H.Root>
  );
}
