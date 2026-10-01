import { FileText, Network, ScrollText, Sparkles } from "lucide-react";
import type { SourceRef } from "@/lib/types";
import { GithubIcon } from "../ui/brand-icons";

export function sourceLabel(source: SourceRef): string {
  if (source.kind === "community") return "Graph theme";
  if (source.kind === "entity") return "Knowledge graph";
  switch (source.docKind) {
    case "cv":
      return "Résumé";
    case "readme":
      return "GitHub README";
    case "repo":
      return "GitHub code analysis";
    case "doc":
      return "GitHub docs";
    case "note":
      return "Note";
    default:
      return "Document";
  }
}

export function SourceIcon({ source, className = "size-3.5" }: { source: SourceRef; className?: string }) {
  if (source.kind === "community") return <Sparkles className={className} />;
  if (source.kind === "entity") return <Network className={className} />;
  if (source.docKind === "cv") return <ScrollText className={className} />;
  if (source.docKind === "readme" || source.docKind === "repo" || source.docKind === "doc")
    return <GithubIcon className={className} />;
  return <FileText className={className} />;
}
