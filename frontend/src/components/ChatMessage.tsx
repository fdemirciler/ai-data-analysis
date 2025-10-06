import React from "react";
import { cn } from "./ui/utils";
import { Bot } from "lucide-react";
import { TableRenderer } from "./renderers/TableRenderer";
import { ChartRenderer } from "./renderers/ChartRenderer";
import { Button } from "./ui/button";

export type Message =
  | {
      id: string;
      role: "user" | "assistant";
      timestamp: Date;
      kind: "text";
      content: string;
    }
  | {
      id: string;
      role: "user" | "assistant";
      timestamp: Date;
      kind: "status";
      content: string;
    }
  | {
      id: string;
      role: "assistant";
      timestamp: Date;
      kind: "error";
      content: string;
    }
  | {
      id: string;
      role: "assistant";
      timestamp: Date;
      kind: "table";
      rows: any[];
    }
  | {
      id: string;
      role: "assistant";
      timestamp: Date;
      kind: "chart";
      chartData: {
        kind: string;
        labels: string[];
        series: { label: string; data: number[] }[];
      };
    };

interface ChatMessageProps {
  message: Message;
  userName: string;
  showCancel?: boolean;
  onCancel?: () => void;
}

export const ChatMessage: React.FC<ChatMessageProps> = ({ message, userName, showCancel, onCancel }) => {
  const isUser = message.role === "user";
  const timeStr = React.useMemo(() => {
    const d = message.timestamp instanceof Date ? message.timestamp : new Date(message.timestamp as any);
    try {
      return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
    } catch {
      return "";
    }
  }, [message.timestamp]);

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
          {message.kind === "text" && (
            <div className="whitespace-pre-wrap break-words">{message.content}</div>
          )}
          {message.kind === "status" && (
            <div className="whitespace-pre-wrap break-words text-muted-foreground italic">
              {message.content}
              {showCancel && (
                <div className="mt-3">
                  <Button variant="outline" size="sm" onClick={onCancel}>
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          )}
          {message.kind === "error" && (
            <div className="whitespace-pre-wrap break-words border border-red-300 bg-red-50 text-red-800 rounded-xl p-4">
              {message.content}
            </div>
          )}
          {message.kind === "table" && <TableRenderer rows={message.rows} />}
          {message.kind === "chart" && <ChartRenderer chartData={message.chartData} />}
          <div className="text-xs text-muted-foreground">{timeStr}</div>
        </div>
      </div>
    </div>
  );
};