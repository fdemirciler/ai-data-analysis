import { Moon, Sun, Menu, HelpCircle } from "lucide-react";
import { Button } from "./ui/button";

interface HeaderProps {
  isDark: boolean;
  onToggleDark: () => void;
  onToggleSidebar: () => void;
}

export function Header({ isDark, onToggleDark, onToggleSidebar }: HeaderProps) {
  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-background/80 backdrop-blur-sm border-b border-border">
      <div className="flex items-center justify-between h-14 px-4">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleSidebar}
          >
            <Menu className="h-4 w-4" />
          </Button>
          <h1 className="font-medium">Data Analysis Chat</h1>
        </div>
        
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              console.log("Help clicked");
            }}
          >
            <HelpCircle className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleDark}
          >
            {isDark ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    </header>
  );
}