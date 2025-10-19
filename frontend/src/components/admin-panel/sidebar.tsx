"use client";
import { SidebarToggle } from "@/components/admin-panel/sidebar-toggle";
import { Button } from "@/components/ui/button";
import { useSidebar } from "@/hooks/use-sidebar";
import { useStore } from "@/hooks/use-store";
import { cn } from "@/lib/utils";
import { PanelsTopLeft } from "lucide-react";
import Link from "next/link";

export function Sidebar({ children }: { children: React.ReactNode }) {
 const sidebar = useStore(useSidebar, (x) => x);
 if (!sidebar) return null;
 const { toggleOpen, getOpenState, setIsHover, settings } = sidebar;
 return (
 <aside
 className={cn(
 "fixed top-0 left-0 z-20 h-screen -translate-x-full lg:translate-x-0 transition-[width] ease-in-out duration-300",
 settings.disabled
 ? "w-0"
 : getOpenState()
 ? "w-72"
 : "w-20"
 )}
 >
 <SidebarToggle isOpen={getOpenState()} setIsOpen={toggleOpen} />
 <div
 onMouseEnter={() => setIsHover(true)}
 onMouseLeave={() => setIsHover(false)}
 className="relative h-full flex flex-col px-3 py-4 overflow-y-auto shadow-md dark:shadow-zinc-800"
 >
 <Button
 className={cn(
 "transition-transform ease-in-out duration-300 mb-1",
 getOpenState() ? "" : "-translate-x-1"
 )}
 variant="link"
 asChild
 >
 <Link href="/dashboard" className="flex items-center gap-2">
 <PanelsTopLeft className="w-6 h-6 mr-1" />
 <h1
 className={cn(
 "font-bold text-lg whitespace-nowrap transition-[transform,opacity,display] ease-in-out duration-300",
 getOpenState()
 ? "translate-x-0 opacity-100"
 : "-translate-x-96 opacity-0 hidden"
 )}
 >
 Brand
 </h1>
 </Link>
 </Button>
 {children}
 </div>
 </aside>
 );
}
