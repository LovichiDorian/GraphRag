import type { UIMessage } from "ai";
import type { GraphHighlight, MessageMetadata, SourceRef } from "./types";

export type ChatDataParts = {
  graph: GraphHighlight;
  sources: { sources: SourceRef[] };
  followups: { questions: string[] };
};

export type ChatMessage = UIMessage<MessageMetadata, ChatDataParts>;
