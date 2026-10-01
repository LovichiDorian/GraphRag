"use client";

import { Moon, Sun } from "lucide-react";
import { toggleTheme } from "@/lib/theme";
import { Button } from "../ui/button";
import { Tooltip } from "../ui/tooltip";

export function ThemeToggle() {
  return (
    <Tooltip content="Light / dark theme" side="bottom">
      <Button
        variant="ghost"
        size="icon"
        aria-label="Toggle light and dark theme"
        onClick={(event) => toggleTheme({ x: event.clientX, y: event.clientY })}
      >
        {/* Both icons are rendered and swapped in CSS, so server and client markup always match. */}
        <Moon className="dark:hidden" />
        <Sun className="hidden dark:block" />
      </Button>
    </Tooltip>
  );
}
