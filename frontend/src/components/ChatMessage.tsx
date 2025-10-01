import React from "react";
import { cn } from "./ui/utils";
import { Bot } from "lucide-react";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface ChatMessageProps {
  message: Message;
  userName: string;
}

export function ChatMessage({ message, userName }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <div className="w-full py-8 px-4">
      <div className={cn("max-w-3xl mx-auto flex gap-6")}> 
        {/* Avatar */}
        <div className="flex-shrink-0">
          {isUser ? (
            <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center">
              {userName.charAt(0).toUpperCase()}
            </div>
          ) : (
            <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center">
              <Bot className="h-5 w-5" />
            </div>
          )}
        </div>

        {/* Message Content */}
        <div className="flex-1 space-y-2 pt-1">
          <div className="whitespace-pre-wrap break-words">
            {message.content}
          </div>
        </div>
      </div>
    </div>
  );
}