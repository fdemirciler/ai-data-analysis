import React from "react";
import { cn } from "./ui/utils";
import { Bot } from "lucide-react";
import { TableRenderer } from "./renderers/TableRenderer";
import { ChartRenderer } from "./renderers/ChartRenderer";
import { Button } from "./ui/button";
import { CopyBlock, dracula } from "react-code-blocks";

export type Message =
  | {
      id: string;
      role: "user" | "assistant";
      timestamp: Date;
      kind: "text";
      content: string;
      meta?: {
        fileName?: string;
        fileSize?: string; // formatted, e.g., "1.2 MB"
        rows?: number;
        columns?: number;
      };
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
    }
  | {
      id: string;
      role: "assistant";
      timestamp: Date;
      kind: "code";
      code: string;
      language?: "python";
      warnings?: string[];
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
  // no-op state for now

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
          {message.kind === "table" && (
            <div className="w-fit max-w-full overflow-auto">
              <TableRenderer rows={message.rows} />
            </div>
          )}
          {message.kind === "chart" && <ChartRenderer chartData={message.chartData} />}
          {message.kind === "code" && (
            <div className="border rounded-xl p-4 bg-background">
              <details>
                <summary className="cursor-pointer select-none font-medium">View generated Python script</summary>
                <div className="mt-3 space-y-3">
                  <div className="text-sm">
                    <CopyBlock
                      text={message.code}
                      language={message.language || "python"}
                      wrapLongLines
                      theme={dracula}
                    />
                  </div>
                  {Array.isArray(message.warnings) && message.warnings.length > 0 && (
                    <div className="mt-2 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-3 dark:text-amber-200 dark:bg-amber-950 dark:border-amber-900">
                      <div className="font-medium mb-1">Validator warnings</div>
                      <ul className="list-disc pl-5 space-y-1">
                        {message.warnings.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </details>
            </div>
          )}
          <div className="text-xs text-muted-foreground flex flex-wrap items-center gap-2">
            <span>{timeStr}</span>
            {message.kind === "text" && message.meta?.fileName && (
              <span className="inline-flex items-center rounded-full border px-2 py-0.5">
                {message.meta.fileName}
              </span>
            )}
            {message.kind === "text" && message.meta?.fileSize && (
              <span className="inline-flex items-center rounded-full border px-2 py-0.5">
                {message.meta.fileSize}
              </span>
            )}
            {message.kind === "text" && message.meta?.rows !== undefined && message.meta?.columns !== undefined && (
              <span className="inline-flex items-center rounded-full border px-2 py-0.5">
                {Number(message.meta.rows).toLocaleString()} rows x {Number(message.meta.columns).toLocaleString()} columns
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};