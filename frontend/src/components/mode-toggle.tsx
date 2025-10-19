"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { MoonIcon, SunIcon } from "@radix-ui/react-icons";

import { Button } from "@/components/ui/button";
import {
 Tooltip,
 TooltipContent,
 TooltipTrigger,
 TooltipProvider
} from "@/components/ui/tooltip";

export function ModeToggle() {
 const { setTheme, theme } = useTheme();

 return (
 <TooltipProvider disableAndForceFocus={true}>
 <Tooltip>
 <TooltipTrigger asChild>
 <Button
 className="h-8 w-8"
 variant="outline"
 size="icon"
 onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
 >
 <SunIcon className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
 <MoonIcon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
 <span className="sr-only">Switch Theme</span>
 </Button>
 </TooltipTrigger>
 <TooltipContent side="bottom">Switch Theme</TooltipContent>
 </Tooltip>
 </TooltipProvider>
 );
}
