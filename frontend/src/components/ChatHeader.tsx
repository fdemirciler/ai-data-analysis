import React from "react";
import { DarkModeToggle } from "./DarkModeToggle";
import { RefreshCw, HelpCircle, Github } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";
import { HelpContent } from './HelpContent';
import { Button, buttonVariants } from './ui/button';

interface ChatHeaderProps {
  sidebarOpen: boolean;
}

export function ChatHeader({ sidebarOpen }: ChatHeaderProps) {
  // Match the sidebar widths: 256px (expanded) or 64px (collapsed)
  const leftOffset = sidebarOpen ? 256 : 64;
  return (
    <header
      className="fixed top-0 right-0 h-14 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 z-50 flex items-center justify-between px-4 transition-all duration-300"
      style={{ left: `${leftOffset}px` }}
    >
      <div className="font-semibold tracking-tight">AI Data Analyst</div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" onClick={() => window.location.reload()}>
          <RefreshCw className="size-4" />
        </Button>
        <DarkModeToggle />
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label="Help"
              className={buttonVariants({ variant: "ghost", size: "icon" })}
            >
              <HelpCircle className="size-4" />
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-80">
            <HelpContent />
          </PopoverContent>
        </Popover>
        <Button variant="ghost" size="icon" onClick={() => window.open('https://github.com/fdemirciler/ai-data-analysis', '_blank')}>
          <Github className="size-4" />
        </Button>
      </div>
    </header>
  );
}