import React, { useState } from "react";
import { 
  MessageCircle, 
  Plus, 
  ChevronLeft, 
  ChevronRight, 
  Trash2, 
  User,
  LogOut,
  Menu
} from "lucide-react";
import { Button } from "./ui/button";
import { ScrollArea } from "./ui/scroll-area";
import { Separator } from "./ui/separator";
import { ChatSession, UsageState } from "../types/chat";

interface NewSidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  onNewChat: () => void;
  onSelectChat: (chatId: string) => void;
  onDeleteChat: (chatId: string) => void;
  onDeleteAllData: () => void;
  onLogout: () => void;
  sessions: ChatSession[];
  activeSessionId: string | null;
  userName: string;
  userEmail: string;
  usage: UsageState;
}

export function NewSidebar({
  isOpen,
  onToggle,
  onNewChat,
  onSelectChat,
  onDeleteChat,
  onDeleteAllData,
  onLogout,
  sessions,
  activeSessionId,
  userName,
  userEmail,
  usage,
}: NewSidebarProps) {
  const usagePercent = Math.round((usage.count / usage.limit) * 100);
  
  // Show only last 5 sessions
  const recentSessions = sessions.slice(0, 5);

  return (
    <>
      {/* Collapsed State - Icon Bar */}
      {!isOpen && (
        <div className="fixed left-0 top-0 h-full w-16 bg-gray-50 dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 z-40 flex flex-col items-center py-4 gap-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggle}
            className="rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800"
          >
            <Menu className="h-5 w-5" />
          </Button>
          
          <Separator className="w-8" />
          
          <Button
            variant="ghost"
            size="icon"
            onClick={onNewChat}
            className="rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800"
            title="New Chat"
          >
            <Plus className="h-5 w-5" />
          </Button>
          
          <div className="flex-1" />
          
          <Button
            variant="ghost"
            size="icon"
            className="rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800"
            title={userName}
          >
            <User className="h-5 w-5" />
          </Button>
        </div>
      )}

      {/* Expanded State - Full Sidebar */}
      {isOpen && (
        <>
          {/* Mobile Overlay */}
          <div 
            className="fixed inset-0 bg-black/50 z-40 md:hidden"
            onClick={onToggle}
          />
          
          {/* Sidebar Panel */}
          <aside className="fixed left-0 top-0 h-full w-80 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 z-50 flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-800">
              <h2 className="font-semibold text-gray-900 dark:text-gray-100">
                Recent Chats
              </h2>
              <Button
                variant="ghost"
                size="icon"
                onClick={onToggle}
                className="rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                <ChevronLeft className="h-5 w-5" />
              </Button>
            </div>

            {/* New Chat Button */}
            <div className="p-4">
              <Button 
                onClick={onNewChat}
                className="w-full justify-start gap-2 bg-gray-900 hover:bg-gray-800 dark:bg-white dark:hover:bg-gray-100 text-white dark:text-gray-900"
              >
                <Plus className="h-4 w-4" />
                New Chat
              </Button>
            </div>

            {/* Chat History - Last 5 */}
            <ScrollArea className="flex-1 px-4">
              <div className="space-y-2 pb-4">
                {recentSessions.length === 0 ? (
                  <div className="text-center py-8 text-sm text-gray-500 dark:text-gray-400">
                    No chat history yet
                  </div>
                ) : (
                  recentSessions.map((session) => (
                    <div
                      key={session.id}
                      className={`
                        group relative flex items-start gap-3 p-3 rounded-lg cursor-pointer
                        transition-colors
                        ${session.id === activeSessionId 
                          ? 'bg-gray-100 dark:bg-gray-800' 
                          : 'hover:bg-gray-50 dark:hover:bg-gray-800/50'
                        }
                      `}
                      onClick={() => onSelectChat(session.id)}
                    >
                      <MessageCircle className="h-4 w-4 mt-0.5 text-gray-400 dark:text-gray-500 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                          {session.title}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {new Date(session.lastActivityAt).toLocaleDateString()}
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteChat(session.id);
                        }}
                        className="opacity-0 group-hover:opacity-100 transition-opacity h-7 w-7"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))
                )}
              </div>
            </ScrollArea>

            {/* User Profile Section */}
            <div className="p-4 border-t border-gray-200 dark:border-gray-800 space-y-4">
              {/* Usage Indicator */}
              <div className="space-y-2">
                <div className="flex justify-between text-xs text-gray-600 dark:text-gray-400">
                  <span>Daily Usage</span>
                  <span className="font-medium">{usage.count} / {usage.limit}</span>
                </div>
                <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-blue-500 dark:bg-blue-400 transition-all"
                    style={{ width: `${usagePercent}%` }}
                  />
                </div>
              </div>

              <Separator />

              {/* User Info */}
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-500 rounded-full flex items-center justify-center text-white font-semibold">
                  {userName.charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                    {userName}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                    {userEmail}
                  </p>
                </div>
              </div>

              {/* Actions */}
              <div className="space-y-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onDeleteAllData}
                  className="w-full justify-start gap-2 text-red-600 hover:text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950"
                >
                  <Trash2 className="h-4 w-4" />
                  Delete All Data
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onLogout}
                  className="w-full justify-start gap-2"
                >
                  <LogOut className="h-4 w-4" />
                  Logout
                </Button>
              </div>
            </div>
          </aside>
        </>
      )}
    </>
  );
}
