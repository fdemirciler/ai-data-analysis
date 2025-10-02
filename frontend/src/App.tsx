import React, { useState, useRef, useEffect } from "react";
import { ChatSidebar } from "./components/ChatSidebar";
import { ChatMessage, type Message } from "./components/ChatMessage";
import { ChatInput } from "./components/ChatInput";
import { ChatHeader } from "./components/ChatHeader";
import { ScrollArea } from "./components/ui/scroll-area";
import { useAuth } from "./context/AuthContext";
import { getSignedUploadUrl, putToSignedUrl, streamChat, type ChatEvent } from "./services/api";

interface Conversation {
  id: string;
  title: string;
  timestamp: Date;
  messages: Message[];
  datasetId?: string;
}

export default function App() {
  const { idToken, loading } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [dailyUsed, setDailyUsed] = useState(3);
  const dailyLimit = 50;
  const [conversations, setConversations] = useState<Conversation[]>([
    {
      id: "1",
      title: "Getting started with React",
      timestamp: new Date(Date.now() - 86400000),
      messages: [
        {
          id: "1-1",
          role: "user",
          content: "How do I get started with React?",
          timestamp: new Date(Date.now() - 86400000),
        },
        {
          id: "1-2",
          role: "assistant",
          content: "Getting started with React is straightforward! Here are the key steps:\n\n1. Install Node.js if you haven't already\n2. Use Create React App or Vite to bootstrap your project\n3. Learn about components, props, and state\n4. Practice building small projects\n\nWould you like me to explain any of these steps in more detail?",
          timestamp: new Date(Date.now() - 86400000),
        },
      ],
    },
    {
      id: "2",
      title: "CSS Grid vs Flexbox",
      timestamp: new Date(Date.now() - 172800000),
      messages: [
        {
          id: "2-1",
          role: "user",
          content: "What's the difference between CSS Grid and Flexbox?",
          timestamp: new Date(Date.now() - 172800000),
        },
        {
          id: "2-2",
          role: "assistant",
          content: "Great question! Here's the main difference:\n\n**Flexbox** is one-dimensional - it handles layout in a single direction (row or column). It's perfect for:\n- Navigation bars\n- Card layouts\n- Centering items\n\n**CSS Grid** is two-dimensional - it handles both rows and columns simultaneously. It's ideal for:\n- Page layouts\n- Complex grid systems\n- Magazine-style designs\n\nIn practice, you'll often use both together!",
          timestamp: new Date(Date.now() - 172800000),
        },
      ],
    },
  ]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>("1");
  const [isTyping, setIsTyping] = useState(false);
  const [uploading, setUploading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevConvIdRef = useRef<string | null>(null);

  const activeConversation = conversations.find((c) => c.id === activeConversationId);

  // Auto-scroll to bottom when new messages or typing indicator changes
  useEffect(() => {
    const behavior: ScrollBehavior =
      prevConvIdRef.current && prevConvIdRef.current === activeConversationId
        ? 'smooth'
        : 'auto';

    // Defer to next frame so DOM has updated
    const id = requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior, block: 'end' });
    });
    prevConvIdRef.current = activeConversationId;
    return () => cancelAnimationFrame(id);
  }, [activeConversationId, activeConversation?.messages.length, isTyping]);

  const handleNewChat = () => {
    const newConversation: Conversation = {
      id: Date.now().toString(),
      title: "New conversation",
      timestamp: new Date(),
      messages: [],
    };
    setConversations([newConversation, ...conversations]);
    setActiveConversationId(newConversation.id);
  };

  const handleSelectConversation = (id: string) => {
    setActiveConversationId(id);
  };

  const handleDeleteConversation = (id: string) => {
    setConversations((prev) => {
      const next = prev.filter((c) => c.id !== id);
      setActiveConversationId((current) => {
        if (current === id) {
          return next.length ? next[0].id : null;
        }
        return current;
      });
      return next;
    });
  };

  const SIGN_URL = (import.meta as any).env?.VITE_SIGN_URL as string | undefined;
  const CHAT_URL = (import.meta as any).env?.VITE_CHAT_URL as string | undefined;

  const ensureConversation = (): string => {
    if (!activeConversationId) {
      const newId = Date.now().toString();
      const newConversation: Conversation = {
        id: newId,
        title: "New conversation",
        timestamp: new Date(),
        messages: [],
      };
      setConversations((prev) => [newConversation, ...prev]);
      setActiveConversationId(newId);
      return newId;
    }
    return activeConversationId;
  };

  const handleUploadFile = async (file: File) => {
    if (!SIGN_URL) {
      alert("Missing VITE_SIGN_URL env");
      return;
    }
    if (loading || !idToken) {
      alert("Authenticating... please retry");
      return;
    }
    setUploading(true);
    try {
      const convId = ensureConversation();
      if (!convId) return;
      const resp = await getSignedUploadUrl({
        signUrl: SIGN_URL,
        idToken,
        sessionId: convId,
        filename: file.name,
        size: file.size,
        type: file.type || "application/octet-stream",
      });
      await putToSignedUrl(resp.url, file);

      // Update conversation with datasetId and add system message
      setConversations((prev) =>
        prev.map((c) =>
          c.id === convId
            ? {
                ...c,
                datasetId: resp.datasetId,
                messages: [
                  ...c.messages,
                  {
                    id: `${convId}-${Date.now()}-sys`,
                    role: "assistant",
                    content: "File uploaded and queued for preprocessing. You can now ask a question about your data.",
                    timestamp: new Date(),
                  } as Message,
                ],
              }
            : c
        )
      );
    } catch (e: any) {
      alert(e?.message || String(e));
    } finally {
      setUploading(false);
    }
  };

  const handleSendMessage = async (content: string) => {
    const convId = ensureConversation();
    if (!convId) return;
    const conv = conversations.find((c) => c.id === convId);
    if (!conv?.datasetId) {
      alert("Please upload a dataset first using the paperclip.");
      return;
    }
    if (loading || !idToken) {
      alert("Authenticating... please retry");
      return;
    }
    if (!CHAT_URL) {
      alert("Missing VITE_CHAT_URL env");
      return;
    }

    // Push user message
    const userMessage: Message = {
      id: `${convId}-${Date.now()}`,
      role: "user",
      content,
      timestamp: new Date(),
    };
    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId
          ? {
              ...c,
              messages: [...c.messages, userMessage],
              title: c.messages.length === 0 ? (content.length > 50 ? content.slice(0, 50) + "..." : content) : c.title,
            }
          : c
      )
    );

    // Start SSE stream
    setIsTyping(true);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await streamChat({
        chatUrl: CHAT_URL,
        idToken,
        sessionId: convId,
        datasetId: conv.datasetId!,
        question: content,
        signal: ac.signal,
        onEvent: (ev: ChatEvent) => {
          if (ev.type === "error") {
            setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...c.messages, { id: `${convId}-${Date.now()}-err`, role: "assistant", content: `Error: ${ev.data.message}`, timestamp: new Date() }] } : c)));
            setIsTyping(false);
          } else if (ev.type === "done") {
            const text = ev.data.summary || "Analysis complete.";
            setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...c.messages, { id: `${convId}-${Date.now()}-ai`, role: "assistant", content: text, timestamp: new Date() }] } : c)));
            setIsTyping(false);
            setDailyUsed((prev) => prev + 1);
          }
        },
      });
    } catch (e) {
      // Network error already surfaced in onEvent or thrown; ensure state cleanup
      setIsTyping(false);
    } finally {
      abortRef.current = null;
      // Fallback: if stream ended without a 'done' event, stop typing indicator
      setIsTyping(false);
    }
  };

  return (
    <div className="size-full flex bg-background">
      {/* Header */}
      <ChatHeader sidebarOpen={sidebarOpen} />

      {/* Sidebar */}
      <ChatSidebar
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelectConversation={handleSelectConversation}
        onNewChat={handleNewChat}
        onDeleteConversation={handleDeleteConversation}
        userName="Fatih Demirciler"
        userPlan="Free"
        dailyLimit={dailyLimit}
        dailyUsed={dailyUsed}
      />

      {/* Main Chat Area */}
      <main
        className="flex-1 flex flex-col h-full transition-all duration-300 pt-14"
        style={{
          marginLeft: sidebarOpen ? "256px" : "64px",
        }}
      >
        {/* Messages */}
        <ScrollArea ref={scrollRef} className="flex-1">
          {activeConversation && activeConversation.messages.length > 0 ? (
            <div className="pb-32">
              {activeConversation.messages.map((message) => (
                <React.Fragment key={message.id}>
                  <ChatMessage
                    message={message}
                    userName="Fatih Demirciler"
                  />
                </React.Fragment>
              ))}
              {isTyping && (
                <div className="w-full py-8 px-4">
                  <div className="max-w-3xl mx-auto flex gap-6">
                    <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center flex-shrink-0">
                      <div className="w-5 h-5">AI</div>
                    </div>
                    <div className="flex-1 pt-1">
                      <div className="flex gap-1">
                        <div className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                        <div className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                        <div className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                      </div>
                    </div>
                  </div>
                </div>
              )}
              {/* Bottom sentinel for smooth scrolling */}
              <div ref={bottomRef} />
            </div>
          ) : (
            <div className="h-full flex items-center justify-center p-8 pb-32">
              <div className="text-center max-w-md">
                <h2 className="mb-4">Start a new conversation</h2>
                <p className="text-muted-foreground">
                  Ask me anything! I'm here to help answer your questions and have a conversation.
                </p>
              </div>
            </div>
          )}
        </ScrollArea>
      </main>

      {/* Fixed Input at Bottom */}
      <div
        className="transition-all duration-300"
        style={{
          marginLeft: sidebarOpen ? "256px" : "64px",
        }}
      >
        <ChatInput onSendMessage={handleSendMessage} onUploadFile={handleUploadFile} disabled={isTyping || uploading} />
      </div>
    </div>
  );
}