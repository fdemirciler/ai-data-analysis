'use client';

import { Ellipsis, LogOut, SquarePen, Trash2, History } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from '@/components/ui/tooltip';

interface Conversation {
  id: string;
  title: string;
}

interface MenuProps {
  isOpen: boolean | undefined;
  conversations: Conversation[];
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onNewChat: () => void;
  onDeleteConversation: (id: string) => void;
  userName: string;
  userPlan: string;
  dailyLimit: number;
  dailyUsed: number;
  onSignOut?: () => void;
}

export function Menu({
  isOpen,
  conversations,
  activeConversationId,
  onSelectConversation,
  onNewChat,
  onDeleteConversation,
  userName,
  userPlan,
  dailyLimit,
  dailyUsed,
  onSignOut,
}: MenuProps) {
  const recentChatsGroup = {
    groupLabel: 'Recent Chats',
    menus: conversations.map((c) => ({
      href: `#`,
      label: c.title,
      active: c.id === activeConversationId,
      icon: History,
      submenus: [],
      id: c.id,
    })),
  };

  return (
    <ScrollArea className="[&>div>div[style]]:!block">
      <nav className="mt-8 h-full w-full">
        <ul className="flex flex-col min-h-[calc(100vh-48px-36px-16px-32px)]">
          {/* New Chat */}
          <li className="px-3 pb-3">
            <Button
              onClick={onNewChat}
              variant="ghost"
              className="w-full justify-start h-10"
            >
              <span className={cn(isOpen === false ? '' : 'mr-4')}>
                <SquarePen size={18} />
              </span>
              <p
                className={cn(
                  'max-w-[150px] truncate',
                  isOpen === false
                    ? '-translate-x-96 opacity-0'
                    : 'translate-x-0 opacity-100'
                )}
              >
                New chat
              </p>
            </Button>
          </li>

          {/* Recent Chats */}
          <li className="px-3 pb-3">
            <p
              className={cn(
                'text-sm font-semibold text-foreground/70 transition-all',
                (isOpen && recentChatsGroup.groupLabel) || isOpen === undefined
                  ? 'pl-3'
                  : 'pl-0 text-center'
              )}
            >
              {(isOpen && recentChatsGroup.groupLabel) ||
              isOpen === undefined ? (
                <>{recentChatsGroup.groupLabel}</>
              ) : !isOpen &&
                isOpen !== undefined &&
                recentChatsGroup.groupLabel ? (
                <TooltipProvider>
                  <Tooltip delayDuration={0}>
                    <TooltipTrigger>
                      <Ellipsis className="w-5 h-5" />
                    </TooltipTrigger>
                    <TooltipContent side="right">
                      <p>{recentChatsGroup.groupLabel}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              ) : (
                <>
                  <Ellipsis className="w-5 h-5" />
                </>
              )}
            </p>
            <ul className="space-y-1 mt-2">
              {recentChatsGroup.menus.map(
                ({ href, label, icon: Icon, active, id }, index) => (
                  <li key={index}>
                    <TooltipProvider delayDuration={0}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="group w-full relative">
                            <Button
                              variant={active ? 'secondary' : 'ghost'}
                              className="w-full justify-start h-10 mb-1"
                              onClick={() => onSelectConversation(id)}
                            >
                              <span
                                className={cn(isOpen === false ? '' : 'mr-4')}
                              >
                                <Icon size={18} />
                              </span>
                              <p
                                className={cn(
                                  'max-w-[150px] truncate',
                                  isOpen === false
                                    ? '-translate-x-96 opacity-0'
                                    : 'translate-x-0 opacity-100'
                                )}
                              >
                                {label}
                              </p>
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label="Delete conversation"
                              className="h-8 w-8 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity absolute right-2 top-1"
                              onClick={(e) => {
                                e.stopPropagation();
                                onDeleteConversation(id);
                              }}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </TooltipTrigger>
                        {isOpen === false && (
                          <TooltipContent side="right">{label}</TooltipContent>
                        )}
                      </Tooltip>
                    </TooltipProvider>
                  </li>
                )
              )}
            </ul>
          </li>

          {/* Footer */}
          <li className="flex-1 px-3 pb-3 flex flex-col justify-end">
            {/* User info */}
            <div className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-secondary cursor-pointer">
              <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center">
                {userName.charAt(0).toUpperCase()}
              </div>
              <div
                className={cn(
                  'flex-1 min-w-0',
                  isOpen === false ? 'hidden' : ''
                )}
              >
                <div className="text-sm truncate">{userName}</div>
                <div className="text-xs text-muted-foreground">{userPlan}</div>
              </div>
            </div>

            {/* Daily Limit */}
            <div
              className={cn(
                'mt-3 px-3 py-2 rounded-lg bg-secondary/50',
                isOpen === false ? 'hidden' : ''
              )}
            >
              <div className="text-xs text-muted-foreground mb-1">
                Daily Limit
              </div>
              <div className="text-sm font-medium">
                {dailyUsed} / {dailyLimit} messages
              </div>
            </div>

            {/* Sign Out */}
            {onSignOut && (
              <div className="mt-3">
                <Button
                  variant="outline"
                  className="w-full justify-center h-10"
                  onClick={onSignOut}
                >
                  <span className={cn(isOpen === false ? '' : 'mr-4')}>
                    <LogOut size={18} />
                  </span>
                  <p
                    className={cn(
                      'whitespace-nowrap',
                      isOpen === false ? 'opacity-0 hidden' : 'opacity-100'
                    )}
                  >
                    Sign out
                  </p>
                </Button>
              </div>
            )}
          </li>
        </ul>
      </nav>
    </ScrollArea>
  );
}