"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronDown, Dot, LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { DropdownMenuArrow } from "@radix-ui/react-dropdown-menu";
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger
} from "@/components/ui/collapsible";
import {
 Tooltip,
 TooltipTrigger,
 TooltipContent,
 TooltipProvider
} from "@/components/ui/tooltip";
import {
 DropdownMenu,
 DropdownMenuItem,
 DropdownMenuLabel,
 DropdownMenuTrigger,
 DropdownMenuContent,
 DropdownMenuSeparator
} from "@/components/ui/dropdown-menu";
import { usePathname } from "next/navigation";

type Submenu = {
 href: string;
 label: string;
 active?: boolean;
};

interface CollapseMenuButtonProps {
 icon: LucideIcon;
 label: string;
 active: boolean;
 submenus: Submenu[];
 isOpen: boolean | undefined;
}

export function CollapseMenuButton({
 icon: Icon,
 label,
 active,
 submenus,
 isOpen
}: CollapseMenuButtonProps) {
 const pathname = usePathname();
 const isSubmenuActive = submenus.some((submenu) =>
 submenu.active === undefined ? submenu.href === pathname : submenu.active
 );
 const [isCollapsed, setIsCollapsed] = useState<boolean>(isSubmenuActive);

 return isOpen ? (
 <Collapsible
 open={isCollapsed}
 onOpenChange={setIsCollapsed}
 className="w-full"
 >
 <CollapsibleTrigger
 className="[&[data-state=open]>div>svg]:rotate-180 mb-1"
 asChild
 >
 <Button
 variant={active ? "secondary" : "ghost"}
 className="w-full justify-start h-10"
 >
 <div className="w-full items-center flex justify-between">
 <div className="flex items-center">
 <Icon className="w-4 h-4 mr-4" />
 <span className="truncate">{label}</span>
 </div>
 <ChevronDown
 className={`w-4 h-4 shrink-0 transition-transform duration-200`}
 />
 </div>
 </Button>
 </CollapsibleTrigger>
 <CollapsibleContent className="data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden">
 <div className="ml-4 pl-2 py-2 space-y-2">
 {submenus.map(({ href, label, active }, index) => (
 <Link
 key={index}
 href={href}
 className={cn(
 "flex items-center gap-x-2 text-sm font-medium text-muted-foreground/80 hover:text-foreground transition-colors",
 active === undefined
 ? pathname === href && "text-foreground"
 : active && "text-foreground"
 )}
 >
 <Dot className="w-5 h-5" />
 <span className="truncate">{label}</span>
 </Link>
 ))}
 </div>
 </CollapsibleContent>
 </Collapsible>
 ) : (
 <DropdownMenu>
 <TooltipProvider delayDuration={0}>
 <Tooltip>
 <TooltipTrigger asChild>
 <DropdownMenuTrigger asChild>
 <Button
 variant={active ? "secondary" : "ghost"}
 className="w-full justify-center h-10"
 >
 <Icon className="w-4 h-4" />
 </Button>
 </DropdownMenuTrigger>
 </TooltipTrigger>
 <TooltipContent side="right" align="start" alignOffset={10}>
 {label}
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <DropdownMenuContent side="right" align="start" sideOffset={15}>
 <DropdownMenuLabel>{label}</DropdownMenuLabel>
 <DropdownMenuSeparator />
 {submenus.map(({ href, label, active }, index) => (
 <DropdownMenuItem key={index} asChild>
 <Link className="w-full" href={href}>
 {label}
 </Link>
 </DropdownMenuItem>
 ))}
 </DropdownMenuContent>
 </DropdownMenu>
 );
}
