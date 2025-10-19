import React, { useState, useRef } from "react";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { cn } from "./ui/utils";
import { Plus, Send } from "lucide-react";

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  onUploadFile?: (file: File) => void | Promise<void>;
  disabled?: boolean;
}

export function ChatInput({ onSendMessage, onUploadFile, disabled }: ChatInputProps) {
  const [message, setMessage] = useState("");
  const [isExpanded, setIsExpanded] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();

    if (message.trim() && !disabled) {
      onSendMessage(message.trim());
      setMessage("");
      setIsExpanded(false);

      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
    }
  };

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setMessage(e.target.value);

    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }

    setIsExpanded(e.target.value.length > 100 || e.target.value.includes("\n"));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="fixed bottom-0 left-0 right-0 bg-gradient-to-t from-background via-background to-transparent pt-8 pb-4 z-30">
      <div className="max-w-3xl mx-auto px-4">
        <form onSubmit={handleSubmit}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            className="hidden"
            onChange={async (e) => {
              const inputEl = e.currentTarget as HTMLInputElement;
              const f = inputEl.files?.[0];
              if (f && onUploadFile && !disabled) {
                try {
                  await onUploadFile(f);
                } finally {
                  if (fileInputRef.current) {
                    fileInputRef.current.value = "";
                  } else {
                    inputEl.value = "";
                  }
                }
              }
            }}
          />

          <div
            className={cn(
              "w-full bg-background dark:bg-muted/50 cursor-text overflow-clip bg-clip-padding p-2.5 shadow-lg border border-border transition-all duration-200",
              {
                "rounded-3xl grid grid-cols-1 grid-rows-[auto_1fr_auto]": isExpanded,
                "rounded-[28px] grid grid-cols-[auto_1fr_auto] grid-rows-[auto_1fr_auto]": !isExpanded,
              }
            )}
            style={{
              gridTemplateAreas: isExpanded
                ? "'header' 'primary' 'footer'"
                : "'header header header' 'leading primary trailing' '. footer .'",
            }}
          >
            <div
              className={cn("flex", { hidden: isExpanded })}
              style={{ gridArea: "leading" }}
            >
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-9 w-9 rounded-full hover:bg-accent outline-none ring-0"
                disabled={disabled}
                onClick={() => fileInputRef.current?.click()}
              >
                <Plus className="size-6 text-muted-foreground shrink-0" />
              </Button>
            </div>

            <div
              className={cn(
                "flex min-h-14 items-center overflow-x-hidden px-1.5",
                {
                  "px-2 py-1 mb-0": isExpanded,
                  "-my-2.5": !isExpanded,
                }
              )}
              style={{ gridArea: "primary" }}
            >
              <div className="flex-1 overflow-auto max-h-52">
                <Textarea
                  ref={textareaRef}
                  value={message}
                  onChange={handleTextareaChange}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask anything"
                  disabled={disabled}
                  className="min-h-0 resize-none rounded-none border-0 p-0 text-base placeholder:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0 scrollbar-thin dark:bg-transparent bg-transparent"
                  rows={1}
                />
              </div>
            </div>

            <div
              className="flex items-center gap-2"
              style={{ gridArea: isExpanded ? "footer" : "trailing" }}
            >
              <div className="ms-auto flex items-center gap-1.5">
                {message.trim() && (
                  <Button
                    type="submit"
                    disabled={disabled}
                    size="icon"
                    className="h-9 w-9 rounded-full"
                  >
                    <Send className="h-5 w-5" />
                  </Button>
                )}
              </div>
            </div>
          </div>
        </form>

        <p className="text-xs text-muted-foreground text-center mt-2">
          Upload CSV/Excel files, 20 MB file limit. Press Enter to send, Shift+Enter for new line.
        </p>
      </div>
    </div>
  );
}
