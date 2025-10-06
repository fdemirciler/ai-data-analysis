import React, { useState, useRef, useEffect } from "react";
import { ChatSidebar } from "./components/ChatSidebar";
import { ChatMessage, type Message } from "./components/ChatMessage";
import { ChatInput } from "./components/ChatInput";
import { ChatHeader } from "./components/ChatHeader";
import { ScrollArea } from "./components/ui/scroll-area";
import { Button } from "./components/ui/button";
import { useAuth } from "./context/AuthContext";
import { ensureSession, updateSessionDataset, saveUserMessage, getRecentSessionsWithMessages } from "./services/firestore";
import { getSignedUploadUrl, putToSignedUrl, streamChat, type ChatEvent } from "./services/api";

interface Conversation {
  id: string;
  title: string;
  timestamp: Date;
  messages: Message[];
  datasetId?: string;
}

export default function App() {
  const { idToken, loading, user } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [dailyUsed, setDailyUsed] = useState(3);
  const dailyLimit = 50;
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [isTyping, setIsTyping] = useState(false);
  const [uploading, setUploading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevConvIdRef = useRef<string | null>(null);
  const placeholderIdRef = useRef<string | null>(null);
  const didInitRef = useRef<boolean>(false);

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
    // Persist session shell
    if (user?.uid) {
      ensureSession(user.uid, newConversation.id, newConversation.title).catch(() => {});
    }
  };

  // Start with a new chat on first mount if nothing is loaded
  useEffect(() => {
    if (didInitRef.current) return;
    didInitRef.current = true;
    if (conversations.length === 0) {
      // Defer to next tick to avoid strict-mode double invokes causing two creations
      setTimeout(() => {
        if (conversations.length === 0) handleNewChat();
      }, 0);
    }
  }, []);

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

  // Cancel current analysis run (abort SSE) and mark placeholder as cancelled
  const handleCancel = () => {
    try {
      abortRef.current?.abort();
    } catch {
      // ignore
    }
    const pid = placeholderIdRef.current;
    const cid = activeConversationId;
    if (pid && cid) {
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== cid) return c;
          const idx = c.messages.findIndex((m) => m.id === pid);
          if (idx === -1) return c;
          const nextMsgs = c.messages.slice();
          const msg = nextMsgs[idx] as Message;
          if (msg.role === "assistant") {
            nextMsgs[idx] = { ...(msg as any), kind: "status", content: "Cancelled." } as Message;
          }
          return { ...c, messages: nextMsgs };
        })
      );
    }
    setIsTyping(false);
    abortRef.current = null;
    placeholderIdRef.current = null;
  };

  // For prod (Hosting), default to relative /api routes via rewrites
  const SIGN_URL = ((import.meta as any).env?.VITE_SIGN_URL as string | undefined) || "/api/sign-upload-url";
  const CHAT_URL = ((import.meta as any).env?.VITE_CHAT_URL as string | undefined) || "/api/chat";

  // Load last ~5 sessions on auth ready
  useEffect(() => {
    (async () => {
      if (!loading && user?.uid) {
        try {
          const sessions = await getRecentSessionsWithMessages(user.uid, 5);
          if (sessions.length > 0) {
            setConversations((prev) => {
              if (!prev || prev.length === 0) return sessions as any;
              const prevIds = new Set(prev.map((c) => c.id));
              const newOnes = sessions.filter((s: any) => !prevIds.has(s.id)) as any;
              return [...prev, ...newOnes];
            });
            setActiveConversationId((prev) => prev ?? sessions[0].id);
          } else {
            // keep defaults / empty
          }
        } catch (_) {
          // ignore load errors in UI
        }
      }
    })();
  }, [loading, user?.uid]);

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
      if (user?.uid) {
        ensureSession(user.uid, newId, newConversation.title).catch(() => {});
      }
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
                    kind: "text",
                    content:
                      "File uploaded and queued for preprocessing. You can now ask a question about your data.",
                    timestamp: new Date(),
                  } as Message,
                ],
              }
            : c
        )
      );
      if (user?.uid) {
        updateSessionDataset(user.uid, convId, resp.datasetId).catch(() => {});
      }
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
      kind: "text",
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
    if (user?.uid) {
      saveUserMessage(user.uid, convId, userMessage.id, content).catch(() => {});
    }

    // Start SSE stream
    setIsTyping(true);
    const ac = new AbortController();
    abortRef.current = ac;
    // Create and push assistant placeholder immediately
    const placeholderId = `${convId}-${Date.now()}-ph`;
    placeholderIdRef.current = placeholderId;
    const placeholder: Message = {
      id: placeholderId,
      role: "assistant",
      kind: "status",
      content: "Analyzing...",
      timestamp: new Date(),
    };
    setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...c.messages, placeholder] } : c)));

    const updatePlaceholder = (updater: (m: Extract<Message, { role: "assistant" }>) => Message) => {
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== convId) return c;
          const idx = c.messages.findIndex((m) => m.id === placeholderId);
          if (idx === -1) return c; // fallback if not found
          const nextMsgs = c.messages.slice();
          nextMsgs[idx] = updater(nextMsgs[idx] as Extract<Message, { role: "assistant" }>);
          return { ...c, messages: nextMsgs };
        })
      );
    };

    try {
      await streamChat({
        chatUrl: CHAT_URL,
        idToken,
        sessionId: convId,
        datasetId: conv.datasetId!,
        question: content,
        signal: ac.signal,
        onEvent: (ev: ChatEvent) => {
          if (ev.type === "validating") updatePlaceholder((m) => ({ ...m, kind: "status", content: "Validating input..." }));
          else if (ev.type === "generating_code") updatePlaceholder((m) => ({ ...m, kind: "status", content: "Generating analysis code..." }));
          else if (ev.type === "running_fast") updatePlaceholder((m) => ({ ...m, kind: "status", content: "Running analysis..." }));
          else if (ev.type === "summarizing") updatePlaceholder((m) => ({ ...m, kind: "status", content: "Summarizing results..." }));
          else if (ev.type === "persisting") updatePlaceholder((m) => ({ ...m, kind: "status", content: "Saving results..." }));
          else if (ev.type === "error") {
            updatePlaceholder((m) => ({ ...m, kind: "error", content: `Error: ${ev.data.message}` }));
            setIsTyping(false);
          } else if (ev.type === "done") {
            const text = ev.data.summary || "Analysis complete.";
            // 1) Turn placeholder into final summary text
            updatePlaceholder((m) => ({ ...m, kind: "text", content: text }));
            // 2) Append table and chart bubbles if present
            const rows = Array.isArray(ev.data.tableSample) ? ev.data.tableSample : [];
            const chartData = ev.data.chartData || null;
            if (rows && rows.length > 0) {
              setConversations((prev) =>
                prev.map((c) =>
                  c.id === convId
                    ? {
                        ...c,
                        messages: [
                          ...c.messages,
                          { id: `${convId}-${Date.now()}-table`, role: "assistant", timestamp: new Date(), kind: "table", rows },
                        ],
                      }
                    : c
                )
              );
            }
            // Only append chart when it has actual data
            const hasChartData = (cd: any): boolean => {
              try {
                const labels = cd?.labels;
                const series = cd?.series;
                if (!Array.isArray(labels) || labels.length === 0) return false;
                if (!Array.isArray(series) || series.length === 0) return false;
                return series.some((s: any) => Array.isArray(s?.data) && s.data.some((x: any) => typeof x === "number"));
              } catch {
                return false;
              }
            };
            if (chartData && hasChartData(chartData)) {
              setConversations((prev) =>
                prev.map((c) =>
                  c.id === convId
                    ? {
                        ...c,
                        messages: [
                          ...c.messages,
                          { id: `${convId}-${Date.now()}-chart`, role: "assistant", timestamp: new Date(), kind: "chart", chartData },
                        ],
                      }
                    : c
                )
              );
            }
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
                      <div className="mt-3">
                        <Button variant="outline" size="sm" onClick={handleCancel}>
                          Cancel
                        </Button>
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