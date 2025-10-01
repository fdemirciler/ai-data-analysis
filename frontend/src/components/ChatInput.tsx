import React, { useState, useRef, useEffect } from "react";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { Paperclip, ArrowUp } from "lucide-react";

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSendMessage, disabled }: ChatInputProps) {
  const [message, setMessage] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
      <div className="relative flex items-end gap-2 bg-background rounded-3xl px-4 py-3 border border-border dark:border-sidebar-border shadow-lg text-foreground dark:text-sidebar-accent-foreground">
          {/* File Upload Button */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-full flex-shrink-0 text-foreground dark:text-sidebar-accent-foreground"
            disabled={disabled}
          >
            <Paperclip className="h-4 w-4 text-foreground dark:text-white" />
          </Button>

          {/* Textarea */}
          <Textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything"
            disabled={disabled}
            className="flex-1 min-h-[24px] max-h-[200px] resize-none border-0 bg-transparent focus-visible:ring-0 focus-visible:ring-offset-0 p-0 placeholder:text-muted-foreground"
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