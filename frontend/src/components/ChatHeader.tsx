import React from "react";
import { DarkModeToggle } from "./DarkModeToggle";

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
      <DarkModeToggle />
    </header>
  );
}