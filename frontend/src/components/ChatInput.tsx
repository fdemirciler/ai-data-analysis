import { useState, useRef } from "react";
import { Send, Paperclip, X } from "lucide-react";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";

interface ChatInputProps {
  onSendMessage: (message: string, file?: File) => Promise<void> | void;
  disabled?: boolean;
  placeholder?: string;
}

export function ChatInput({ 
  onSendMessage, 
  disabled = false, 
  placeholder = "Ask a question about your data..." 
}: ChatInputProps) {
  const [message, setMessage] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim() && !selectedFile) return;

    await onSendMessage(message.trim(), selectedFile || undefined);
    setMessage("");
    setSelectedFile(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit(e);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (file.size > 20 * 1024 * 1024) {
        alert("File size must be less than 20MB");
        return;
      }
      setSelectedFile(file);
    }
  };

  const removeFile = () => {
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 bg-background/80 backdrop-blur-sm border-t border-border">
      <div className="max-w-4xl mx-auto p-4 px-8">
        <form onSubmit={handleSubmit} className="space-y-3">
          {selectedFile && (
            <div className="flex items-center gap-2 p-2 bg-muted rounded-lg">
              <Paperclip className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm text-muted-foreground flex-1">
                {selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={removeFile}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          )}

          <div className="relative">
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileSelect}
              accept=".csv,.xlsx,.xls,.json,.txt"
              className="hidden"
            />
            
            <div className="absolute left-3 bottom-3 z-10">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                disabled={disabled}
                className="h-6 w-6 p-0 hover:bg-muted/50"
              >
                <Paperclip className="h-4 w-4" />
              </Button>
            </div>

            <Textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              disabled={disabled}
              className="min-h-[44px] max-h-32 resize-none pl-12 pr-12"
              rows={1}
            />
            
            <div className="absolute right-3 bottom-3 z-10">
              <Button
                type="submit"
                disabled={disabled || (!message.trim() && !selectedFile)}
                size="sm"
                className="h-6 w-6 p-0"
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <p className="text-xs text-muted-foreground text-center">
            Press Enter to send, Shift+Enter for new line. Supports CSV, Excel, JSON files up to 20MB.
          </p>
        </form>
      </div>
    </div>
  );
}