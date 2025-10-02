import React, { useState, useRef, useEffect } from "react";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { Paperclip, ArrowUp } from "lucide-react";

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  onUploadFile?: (file: File) => void | Promise<void>;
  disabled?: boolean;
}

export function ChatInput({ onSendMessage, onUploadFile, disabled }: ChatInputProps) {
  const [message, setMessage] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = () => {
    if (message.trim() && !disabled) {
      onSendMessage(message.trim());
      setMessage("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [message]);

  return (
    <div className="fixed bottom-0 left-0 right-0 bg-gradient-to-t from-background via-background to-transparent pt-8 pb-4 z-30">
      <div className="max-w-3xl mx-auto px-4">
        <div className="group relative flex items-end gap-2 rounded-3xl px-4 py-3 border border-border bg-input-background/90 dark:bg-sidebar-accent/60 dark:border-sidebar-border shadow-lg text-foreground dark:text-sidebar-accent-foreground transition-all duration-300
        focus-within:-translate-y-1 focus-within:shadow-2xl focus-within:ring-[6px] focus-within:ring-white/50 dark:focus-within:ring-white/25
        focus-within:border-foreground/40 dark:focus-within:border-white/35 has-[textarea:not(:placeholder-shown)]:-translate-y-1 has-[textarea:not(:placeholder-shown)]:ring-[8px] has-[textarea:not(:placeholder-shown)]:ring-white/60 dark:has-[textarea:not(:placeholder-shown)]:ring-white/40">
          {/* File Upload Button */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-full flex-shrink-0 text-foreground dark:text-sidebar-accent-foreground"
            disabled={disabled}
            onClick={() => fileInputRef.current?.click()}
          >
            <Paperclip className="h-4 w-4 text-foreground dark:text-white" />
          </Button>

          {/* Hidden file input */}
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
                  // Reset input so selecting same file again still fires change
                  if (fileInputRef.current) {
                    fileInputRef.current.value = "";
                  } else {
                    inputEl.value = "";
                  }
                }
              }
            }}
          />

          {/* Textarea */}
          <Textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything"
            disabled={disabled}
            className="flex-1 min-h-[24px] max-h-[200px] resize-none border-0 bg-transparent focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 p-0 placeholder:text-muted-foreground group-focus-within:text-foreground"
            rows={1}
          />

          {/* Send Button */}
          {message.trim() && (
            <Button
              onClick={handleSubmit}
              disabled={disabled}
              size="icon"
              className="h-8 w-8 rounded-full bg-primary text-primary-foreground hover:bg-primary/90 flex-shrink-0"
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
          )}
        </div>
        
        <p className="text-xs text-muted-foreground text-center mt-2">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}