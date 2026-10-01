import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatMs(ms?: number | null) {
  if (ms == null) return "";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function hostOf(url: string | null | undefined) {
  if (!url) return "";
  try {
    return new URL(url, "https://graphrag.dorianlovichi.com").hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}
