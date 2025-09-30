import React from "react";
import { Menu, Moon, Sun } from "lucide-react";
import { Button } from "./ui/button";

interface FloatingControlsProps {
  onToggleSidebar: () => void;
  isDark: boolean;
  onToggleDark: () => void;
}

export function FloatingControls({ 
  onToggleSidebar, 
  isDark, 
  onToggleDark 
}: FloatingControlsProps) {
  return (
    <div className="fixed top-0 left-0 right-0 z-20 pointer-events-none">
      <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
        {/* Left: Sidebar Toggle */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggleSidebar}
          className="pointer-events-auto rounded-xl bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm hover:bg-white dark:hover:bg-gray-800 shadow-sm border border-gray-200 dark:border-gray-700"
        >
          <Menu className="h-5 w-5" />
        </Button>

        {/* Right: Theme Toggle */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggleDark}
          className="pointer-events-auto rounded-xl bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm hover:bg-white dark:hover:bg-gray-800 shadow-sm border border-gray-200 dark:border-gray-700"
        >
          {isDark ? (
            <Sun className="h-5 w-5" />
          ) : (
            <Moon className="h-5 w-5" />
          )}
        </Button>
      </div>
    </div>
  );
}
