"use client";

import { create } from "zustand";
import type { GraphHighlight } from "./types";

type Tab = "ask" | "fit";

interface UIState {
  tab: Tab;
  highlight: GraphHighlight | null;
  selectedId: string | null;
  hoveredId: string | null;
  mode: "3d" | "2d";
  pendingQuestion: string | null;
  hiddenTypes: string[];
  setTab: (tab: Tab) => void;
  setHighlight: (highlight: GraphHighlight | null) => void;
  select: (id: string | null) => void;
  hover: (id: string | null) => void;
  setMode: (mode: "3d" | "2d") => void;
  ask: (question: string) => void;
  consumeQuestion: () => string | null;
  toggleType: (type: string) => void;
}

export const useUI = create<UIState>((set, get) => ({
  tab: "ask",
  highlight: null,
  selectedId: null,
  hoveredId: null,
  mode: "3d",
  pendingQuestion: null,
  hiddenTypes: [],
  setTab: (tab) => set({ tab }),
  setHighlight: (highlight) => set({ highlight }),
  select: (selectedId) => set({ selectedId }),
  hover: (hoveredId) => set({ hoveredId }),
  setMode: (mode) => set({ mode }),
  ask: (question) => set({ pendingQuestion: question, tab: "ask", selectedId: null }),
  consumeQuestion: () => {
    const question = get().pendingQuestion;
    if (question) set({ pendingQuestion: null });
    return question;
  },
  toggleType: (type) =>
    set((state) => ({
      hiddenTypes: state.hiddenTypes.includes(type)
        ? state.hiddenTypes.filter((t) => t !== type)
        : [...state.hiddenTypes, type],
    })),
}));
