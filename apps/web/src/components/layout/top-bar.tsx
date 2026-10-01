"use client";

import { Download, Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Kbd } from "../ui/badge";
import { GithubIcon, LinkedinIcon } from "../ui/brand-icons";
import { Button } from "../ui/button";
import { ThemeToggle } from "./theme-toggle";

export function Logo() {
  return (
    <Link href="/" className="group flex items-center gap-2.5" aria-label="Home">
      <span className="relative grid size-8 place-items-center rounded-lg bg-gradient-to-br from-violet-500 to-cyan-400 text-[13px] font-bold text-white shadow-[0_0_24px_-4px_rgb(139_92_246/0.8)]">
        DL
      </span>
      <span className="hidden leading-tight sm:block">
        <span className="block text-sm font-semibold text-fg">Dorian Lovichi</span>
        <span className="block text-[11px] text-fg-muted">Career Knowledge Graph</span>
      </span>
    </Link>
  );
}

export function TopBar({ onSearch }: { onSearch?: () => void }) {
  const pathname = usePathname();
  return (
    <header className="relative z-20 flex h-14 shrink-0 items-center gap-3 px-3 sm:px-5">
      <Logo />
      <nav className="ml-2 hidden items-center gap-1 md:flex" aria-label="Main">
        {[
          { href: "/", label: "Explore" },
          { href: "/how-it-works", label: "How it works" },
        ].map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm transition",
              pathname === item.href ? "bg-tint/[0.07] text-fg" : "text-fg-muted hover:text-fg",
            )}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-1.5">
        {onSearch && (
          <Button
            variant="outline"
            size="sm"
            onClick={onSearch}
            className="hidden text-fg-muted sm:inline-flex"
          >
            <Search /> Search the graph <Kbd>⌘K</Kbd>
          </Button>
        )}
        <ThemeToggle />
        <Button variant="ghost" size="icon" asChild>
          <a href="https://github.com/LovichiDorian" target="_blank" rel="noreferrer" aria-label="GitHub">
            <GithubIcon />
          </a>
        </Button>
        <Button variant="ghost" size="icon" asChild>
          <a
            href="https://linkedin.com/in/dorian-lovichi"
            target="_blank"
            rel="noreferrer"
            aria-label="LinkedIn"
          >
            <LinkedinIcon />
          </a>
        </Button>
        <Button variant="primary" size="sm" asChild>
          <a href="/dorian-lovichi-resume.pdf" download>
            <Download /> <span className="hidden sm:inline">Résumé</span>
          </a>
        </Button>
      </div>
    </header>
  );
}
