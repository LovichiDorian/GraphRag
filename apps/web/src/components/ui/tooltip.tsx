"use client";

import { Tooltip as T } from "radix-ui";
import type { ReactNode } from "react";

export function Tooltip({
  content,
  children,
  side = "top",
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
}) {
  return (
    <T.Provider delayDuration={150}>
      <T.Root>
        <T.Trigger asChild>{children}</T.Trigger>
        <T.Portal>
          <T.Content
            side={side}
            sideOffset={6}
            className="z-50 max-w-80 rounded-lg border border-tint/10 bg-popover/95 px-3 py-2 text-xs leading-relaxed text-fg-soft shadow-2xl backdrop-blur-xl"
          >
            {content}
            <T.Arrow className="fill-popover" />
          </T.Content>
        </T.Portal>
      </T.Root>
    </T.Provider>
  );
}
