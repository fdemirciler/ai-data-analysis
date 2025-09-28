import { useEffect, useRef } from "react";
import { ChatMessage } from "./ChatMessage";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  code?: string;
  chart?: any;
  table?: Array<Record<string, any>>;
  artifacts?: Array<{ type: string; url: string; filename: string }>;
  isStreaming?: boolean;
}

interface ChatAreaProps {
  messages: Message[];
}

export function ChatArea({ messages }: ChatAreaProps) {
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-4xl font-semibold text-gray-700 dark:text-gray-300">ChatGPT</h1>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-hidden">
      <div className="h-full overflow-y-auto" ref={scrollAreaRef}>
        <div className="pt-14 pb-32">
          {messages.map((message) => (
            <ChatMessage
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

          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}