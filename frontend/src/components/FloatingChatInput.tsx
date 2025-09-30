import React, { useState, useRef, KeyboardEvent, ChangeEvent } from "react";
import { ArrowUp, Paperclip, X } from "lucide-react";

interface FloatingChatInputProps {
  onSendMessage: (content: string, file?: File) => void;
  disabled?: boolean;
}

export function FloatingChatInput({ onSendMessage, disabled }: FloatingChatInputProps) {
  const [message, setMessage] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = () => {
    if ((!message.trim() && !file) || disabled) return;
    
    onSendMessage(message, file || undefined);
    setMessage("");
    setFile(null);
    
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setMessage(e.target.value);
    
    // Auto-resize textarea
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  };

  const handleFileSelect = (e: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
    }
  };

  const removeFile = () => {
    setFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const canSend = (message.trim() || file) && !disabled;

  return (
    <div className="fixed bottom-0 left-0 right-0 z-30 pointer-events-none">
      <div className="max-w-3xl mx-auto px-4 pb-8 pointer-events-auto">
        <div className="relative">
          {/* File Preview */}
          {file && (
            <div className="mb-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl px-4 py-2.5 shadow-sm">
              <div className="flex items-center gap-3">
                <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-blue-50 dark:bg-blue-950 flex items-center justify-center">
                  <Paperclip className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                    {file.name}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {(file.size / 1024).toFixed(1)} KB
                  </p>
                </div>
                <button
                  onClick={removeFile}
                  className="flex-shrink-0 p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-md transition-colors"
                >
                  <X className="h-4 w-4 text-gray-500" />
                </button>
              </div>
            </div>
          )}

          {/* Main Input Container */}
          <div className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-3xl shadow-lg hover:shadow-xl transition-shadow">
            <div className="flex items-end gap-2 p-3">
              {/* Attach Button */}
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={disabled}
                className="flex-shrink-0 p-2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="Attach file"
              >
                <Paperclip className="h-5 w-5" />
              </button>
              
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={handleFileSelect}
                className="hidden"
              />

              {/* Text Input */}
              <textarea
                ref={textareaRef}
                value={message}
                onChange={handleChange}
                onKeyDown={handleKeyDown}
                placeholder="Message AI Data Analyst..."
                disabled={disabled}
                rows={1}
                className="flex-1 resize-none bg-transparent text-[15px] text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none disabled:opacity-50 max-h-[200px] py-2"
                style={{ minHeight: "24px" }}
              />

              {/* Send Button */}
              <button
                onClick={handleSubmit}
                disabled={!canSend}
                className={`flex-shrink-0 p-2 rounded-lg transition-all ${
                  canSend
                    ? "bg-gray-900 dark:bg-white text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100"
                    : "bg-gray-100 dark:bg-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed"
                }`}
                title="Send message"
              >
                <ArrowUp className="h-5 w-5" strokeWidth={2.5} />
              </button>
            </div>
          </div>

          {/* Helper Text */}
          <div className="mt-2 px-4 text-center text-xs text-gray-500 dark:text-gray-400">
            <span className="hidden sm:inline">
              <kbd className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 rounded text-[10px] font-mono">⏎</kbd> to send • 
              <kbd className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 rounded text-[10px] font-mono ml-1">⇧⏎</kbd> for new line • 
            </span>
            CSV & Excel up to 20MB
          </div>
        </div>
      </div>
    </div>
  );
}
