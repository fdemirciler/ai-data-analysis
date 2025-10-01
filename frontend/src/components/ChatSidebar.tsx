import React from "react";
import { Button } from "./ui/button";
import { ScrollArea } from "./ui/scroll-area";
import { PanelLeftClose, PanelLeft, SquarePen, MessageSquare, Trash2 } from "lucide-react";
import { cn } from "./ui/utils";

interface Conversation {
  id: string;
  title: string;
  timestamp: Date;
}

interface ChatSidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  conversations: Conversation[];
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onNewChat: () => void;
  userName: string;
  userPlan: string;
  dailyLimit: number;
  dailyUsed: number;
  onDeleteConversation: (id: string) => void;
}

export function ChatSidebar({
  isOpen,
  onToggle,
  conversations,
  activeConversationId,
  onSelectConversation,
  onNewChat,
  userName,
  userPlan,
  dailyLimit,
  dailyUsed,
  onDeleteConversation,
}: ChatSidebarProps) {
  return (
    <>
      {/* Sidebar */}
      <aside
        className={cn(
          "fixed left-0 top-0 h-full bg-sidebar border-r border-sidebar-border transition-all duration-300 flex flex-col z-40",
          isOpen ? "w-64" : "w-16"
        )}
      >
        {isOpen ? (
          <>
            {/* Header - Expanded */}
            <div className="p-3 flex items-center justify-between border-b border-sidebar-border">
              <Button
                onClick={onNewChat}
                variant="ghost"
                className="flex-1 flex items-center justify-start gap-2"
              >
                <SquarePen className="h-4 w-4" />
                New chat
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={onToggle}
                className="ml-2"
              >
                <PanelLeftClose className="h-5 w-5" />
              </Button>
            </div>

            {/* Chat History */}
            <ScrollArea className="flex-1 px-2 py-2">
              <div className="space-y-1">
                {conversations.map((conversation) => (
                  <div
                    key={conversation.id}
                    className={cn(
                      "group w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors",
                      activeConversationId === conversation.id
                        ? "bg-sidebar-accent text-sidebar-accent-foreground"
                        : "hover:bg-sidebar-accent/50 text-sidebar-foreground"
                    )}
                  >
                    <button
                      onClick={() => onSelectConversation(conversation.id)}
                      className="flex items-center gap-3 flex-1 text-left"
                    >
                      <MessageSquare className="h-4 w-4 flex-shrink-0" />
                      <span className="truncate flex-1 text-sm">
                        {conversation.title}
                      </span>
                    </button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Delete conversation"
                      className={cn(
                        "h-8 w-8 shrink-0",
                        activeConversationId === conversation.id
                          ? "text-sidebar-accent-foreground"
                          : "text-sidebar-foreground"
                      ) + " opacity-0 group-hover:opacity-100 transition-opacity"}
                      onClick={() => onDeleteConversation(conversation.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            </ScrollArea>

            {/* User Profile */}
            <div className="border-t border-sidebar-border p-3">
              <div className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-sidebar-accent/50 cursor-pointer transition-colors">
                <div className="w-8 h-8 rounded-full bg-sidebar-primary flex items-center justify-center text-sidebar-primary-foreground">
                  {userName.charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate">{userName}</div>
                  <div className="text-xs text-muted-foreground">{userPlan}</div>
                </div>
              </div>
              
              {/* Daily Limit */}
              <div className="mt-3 px-3 py-2 rounded-lg bg-sidebar-accent/30">
                <div className="text-xs text-muted-foreground mb-1">Daily Limit</div>
                <div className="text-sm">
                  {dailyUsed} / {dailyLimit} messages
                </div>
              </div>
            </div>
          </>
        ) : (
          <>
            {/* Header - Collapsed */}
            <div className="p-2 flex flex-col items-center gap-2 border-b border-sidebar-border">
              <Button
                variant="ghost"
                size="icon"
                onClick={onToggle}
              >
                <PanelLeft className="h-5 w-5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={onNewChat}
                title="New chat"
              >
                <SquarePen className="h-5 w-5" />
              </Button>
            </div>

            {/* Empty space when collapsed - no chat history icons */}
            <div className="flex-1" />

            {/* User Profile - Collapsed */}
            <div className="border-t border-sidebar-border p-2 flex flex-col items-center gap-2">
              <Button
                variant="ghost"
                size="icon"
                title={`${userName} (${userPlan})`}
              >
                <div className="w-6 h-6 rounded-full bg-sidebar-primary flex items-center justify-center text-sidebar-primary-foreground text-xs">
                  {userName.charAt(0).toUpperCase()}
                </div>
              </Button>
            </div>
          </>
        )}
      </aside>
    </>
  );
}