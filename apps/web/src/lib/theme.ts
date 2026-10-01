"use client";

import { useSyncExternalStore } from "react";

import { THEME_COLORS, THEME_STORAGE_KEY, type Theme } from "./theme-script";

export type { Theme };

function read(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

/** The active theme; components re-render when <html data-theme> changes. */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, read, () => "light");
}

function apply(theme: Theme) {
  const root = document.documentElement;
  // Freeze CSS transitions so every surface switches in the same frame.
  const freeze = document.createElement("style");
  freeze.textContent = "*,*::before,*::after{transition:none!important}";
  document.head.appendChild(freeze);
  if (theme === "dark") root.dataset.theme = "dark";
  else delete root.dataset.theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLORS[theme]);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Private mode or blocked storage: the choice simply isn't remembered.
  }
  void window.getComputedStyle(document.body).opacity; // flush styles before re-enabling transitions
  window.setTimeout(() => freeze.remove(), 0);
}

/** Toggle the theme with a circular reveal centred on the pointer (View Transitions API). */
export function toggleTheme(origin?: { x: number; y: number }) {
  const next: Theme = read() === "dark" ? "light" : "dark";
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (typeof document.startViewTransition !== "function" || reduced) {
    apply(next);
    return;
  }
  const x = origin?.x ?? window.innerWidth - 40;
  const y = origin?.y ?? 28;
  const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
  const transition = document.startViewTransition(() => apply(next));
  void transition.ready.then(() => {
    document.documentElement.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
      { duration: 550, easing: "cubic-bezier(0.4, 0, 0.2, 1)", pseudoElement: "::view-transition-new(root)" },
    );
  });
}
