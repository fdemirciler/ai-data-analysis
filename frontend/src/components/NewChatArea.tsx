import React, { useEffect, useRef } from "react";
import { ChatMessage as ChatMessageComponent } from "./ChatMessage";
import { ChatMessage } from "../types/chat";

interface NewChatAreaProps {
  messages: ChatMessage[];
  isLoading?: boolean;
}

export function NewChatArea({ messages, isLoading }: NewChatAreaProps) {
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center px-4">
        <div className="text-center max-w-2xl">
          <div className="mb-6">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center">
              <svg 
                className="w-8 h-8 text-white" 
                fill="none" 
                stroke="currentColor" 
                viewBox="0 0 24 24"
              >
                <path 
                  strokeLinecap="round" 
                  strokeLinejoin="round" 
                  strokeWidth={2} 
                  d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" 
                />
              </svg>
            </div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100 mb-2">
              AI Data Analyst
            </h1>
            <p className="text-gray-600 dark:text-gray-400 mb-8">
              Upload your data and ask questions to get instant insights
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-left">
            <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-2">
                📊 Analyze Data
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Upload CSV or Excel files and ask questions about your data
              </p>
            </div>
            <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-2">
                🤖 AI-Powered
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Get instant insights powered by advanced AI models
              </p>
            </div>
            <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-2">
                📈 Visualizations
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Automatic charts and graphs to understand your data better
              </p>
            </div>
            <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-2">
                ⚡ Fast Results
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Real-time streaming responses as analysis progresses
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-hidden bg-transparent">
      <div 
        className="h-full overflow-y-auto scroll-smooth"
        ref={scrollAreaRef}
      >
        {/* Top padding to prevent content hiding under floating controls */}
        <div className="pt-4 pb-48">
          {messages.map((message) => (
            <ChatMessageComponent
              key={message.id}
              role={message.role}
              content={message.content}
              timestamp={message.timestamp}
              code={message.code}
              chart={message.chart}
              table={message.table}
              artifacts={message.artifacts}
              isStreaming={message.isStreaming}
            />
          ))}
          
          {/* Scroll anchor */}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
