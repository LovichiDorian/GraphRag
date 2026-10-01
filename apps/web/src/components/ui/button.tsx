import { Slot } from "radix-ui";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

const variants = {
  primary:
    "bg-gradient-to-r from-violet-500 to-cyan-500 text-white shadow-[0_8px_30px_-8px_rgb(139_92_246/0.6)] hover:brightness-110",
  ghost: "text-fg-soft hover:bg-tint/[0.06] hover:text-fg",
  outline: "border border-tint/10 bg-tint/[0.03] text-fg-soft hover:bg-tint/[0.07] hover:text-fg",
  subtle: "bg-tint/[0.06] text-fg hover:bg-tint/[0.1]",
} as const;

const sizes = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
  lg: "h-11 px-5 text-sm gap-2",
  icon: "size-9",
} as const;

type Props = ComponentProps<"button"> & {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
  asChild?: boolean;
};

export function Button({ variant = "outline", size = "md", asChild, className, ...props }: Props) {
  const Component = asChild ? Slot.Root : "button";
  return (
    <Component
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-lg font-medium transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-violet-400/60 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  );
}
