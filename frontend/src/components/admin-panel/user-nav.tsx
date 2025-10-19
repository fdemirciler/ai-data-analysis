"use client";

import Link from "next/link";
import { LayoutGrid, LogOut, User } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
 Tooltip,
 TooltipContent,
 TooltipTrigger,
 TooltipProvider
} from "@/components/ui/tooltip";
import {
 DropdownMenu,
 DropdownMenuContent,
 DropdownMenuGroup,
 DropdownMenuItem,
 DropdownMenuLabel,
 DropdownMenuSeparator,
 DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";

export function UserNav() {
 return (
 <DropdownMenu>
 <TooltipProvider disableAndForceFocus={true}>
 <Tooltip>
 <TooltipTrigger asChild>
 <DropdownMenuTrigger asChild>
 <Button
 variant="outline"
 className="relative h-8 w-8 rounded-full"
 >
 <Avatar className="h-8 w-8">
 <AvatarImage src="#" alt="@shadcn" />
 <AvatarFallback>JD</AvatarFallback>
 </Avatar>
 </Button>
 </DropdownMenuTrigger>
 </TooltipTrigger>
 <TooltipContent side="bottom">Profile</TooltipContent>
 </Tooltip>
 </TooltipProvider>

 <DropdownMenuContent className="w-56" align="end" forceMount>
 <DropdownMenuLabel className="font-normal">
 <div className="flex flex-col space-y-1">
 <p className="text-sm font-medium leading-none">John Doe</p>
 <p className="text-xs leading-none text-muted-foreground">
 johndoe@example.com
 </p>
 </div>
 </DropdownMenuLabel>
 <DropdownMenuSeparator />
 <DropdownMenuGroup>
 <DropdownMenuItem>
 <LayoutGrid className="w-4 h-4 mr-2" />
 Dashboard
 </DropdownMenuItem>
 <DropdownMenuItem>
 <User className="w-4 h-4 mr-2" />
 Account
 </DropdownMenuItem>
 </DropdownMenuGroup>
 <DropdownMenuSeparator />
 <DropdownMenuItem onClick={() => {}}>
 <LogOut className="w-4 h-4 mr-2" />
 Sign out
 </DropdownMenuItem>
 </DropdownMenuContent>
 </DropdownMenu>
 );
}
