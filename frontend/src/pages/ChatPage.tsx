import React, { useState, useRef, useEffect } from "react";
import { ChatSidebar } from "../components/ChatSidebar";
import { ChatMessage, type Message } from "../components/ChatMessage";
import { ChatInput } from "../components/ChatInput";
import { ChatHeader } from "../components/ChatHeader";
import { ScrollArea } from "../components/ui/scroll-area";
import { useAuth } from "../context/AuthContext";
import {
  ensureSession,
  updateSessionDataset,
  saveUserMessage,
  getRecentSessionsWithMessages,
  subscribeDatasetMeta,
  subscribeUserProfile,
  incrementDailyUsage,
  saveAssistantMessage,
  resetDailyIfNeeded,
  updateSessionTitle,
  subscribeRecentSessionTitles,
} from "../services/firestore";
import { getSignedUploadUrl, putToSignedUrl, streamChat, type ChatEvent } from "../services/api";
import { generateTitleLocal } from "../utils/generateTitle";

interface Conversation {
  id: string;
  title: string;
  timestamp: Date;
  messages: Message[];
  datasetId?: string;
}

interface UserProfile {
  displayName?: string;
  email?: string;
  plan?: string;
  quota?: number;
  messagesToday?: number;
}

export default function ChatPage() {
  const RECENT_TAKE = 10;
  const { idToken, loading, user, signOut } = useAuth() as any;
  const [sidebarOpen, setSidebarOpen] = useState(false);
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
  const datasetMetaSubsRef = useRef<Record<string, () => void>>({});
  const uploadMsgIdByConvRef = useRef<Record<string, string | null>>({});
  const codeInsertedByConvRef = useRef<Record<string, boolean>>({});
  const codeMsgIdByConvRef = useRef<Record<string, string | null>>({});
  const summaryStreamTimerRef = useRef<number | null>(null);
  const summaryStreamingRef = useRef<boolean>(false);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const titleLockedRef = useRef<Record<string, boolean>>({});

  const dailyLimit = profile?.quota ?? 50;
  const dailyUsed = profile?.messagesToday ?? 0;
  const userName = user?.displayName || user?.email || "User";

  const formatBytes = (bytes: number): string => {
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    const val = bytes / Math.pow(k, i);
    return `${val.toFixed(val >= 100 ? 0 : val >= 10 ? 1 : 2)} ${sizes[i]}`;
  };

  const activeConversation = conversations.find((c) => c.id === activeConversationId);

  useEffect(() => {
    const behavior: ScrollBehavior =
      prevConvIdRef.current && prevConvIdRef.current === activeConversationId
        ? "smooth"
        : "auto";
    const id = requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior, block: "end" });
    });
    prevConvIdRef.current = activeConversationId;
    return () => cancelAnimationFrame(id);
  }, [activeConversationId, activeConversation?.messages.length, isTyping]);

  useEffect(() => {
    if (!loading && user?.uid) {
      const unsub = subscribeUserProfile(user.uid, async (p) => {
        setProfile(p);
        try { await resetDailyIfNeeded(user.uid, p?.lastReset); } catch {}
      });
      return () => {
        try { unsub(); } catch {}
      };
    }
  }, [loading, user?.uid]);

  const handleNewChat = () => {
    const newConversation: Conversation = {
      id: Date.now().toString(),
      title: "New conversation",
      timestamp: new Date(),
      messages: [],
    };
    setConversations((prev) => [newConversation, ...prev].slice(0, RECENT_TAKE));
    setActiveConversationId(newConversation.id);
    if (user?.uid) {
      ensureSession(user.uid, newConversation.id, newConversation.title).catch(() => {});
    }
  };

  // Removed auto-creation of a placeholder session on mount.

  useEffect(() => {
    return () => {
      if (summaryStreamTimerRef.current !== null) {
        window.clearInterval(summaryStreamTimerRef.current);
        summaryStreamTimerRef.current = null;
      }
      summaryStreamingRef.current = false;
    };
  }, []);

  const handleSelectConversation = (id: string) => {
    setActiveConversationId(id);
  };

  const handleDeleteConversation = (id: string) => {
    try {
      datasetMetaSubsRef.current[id]?.();
      delete datasetMetaSubsRef.current[id];
    } catch {}
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

  const handleCancel = () => {
    try {
      abortRef.current?.abort();
    } catch {}
    if (summaryStreamTimerRef.current !== null) {
      window.clearInterval(summaryStreamTimerRef.current);
      summaryStreamTimerRef.current = null;
    }
    summaryStreamingRef.current = false;
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

  const SIGN_URL = ((import.meta as any).env?.VITE_SIGN_URL as string | undefined) || "/api/sign-upload-url";
  const CHAT_URL = ((import.meta as any).env?.VITE_CHAT_URL as string | undefined) || "/api/chat";

  useEffect(() => {
    (async () => {
      if (!loading && user?.uid) {
        try {
          const sessions = await getRecentSessionsWithMessages(user.uid, RECENT_TAKE);
          if (sessions.length > 0) {
            setConversations((prev) => {
              if (!prev || prev.length === 0) return sessions as any;
              const prevIds = new Set(prev.map((c) => c.id));
              const newOnes = sessions.filter((s: any) => !prevIds.has(s.id)) as any;
              const merged = [...prev, ...newOnes];
              merged.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());
              return merged.slice(0, RECENT_TAKE);
            });
            setActiveConversationId((prev) => prev ?? sessions[0].id);
          }
        } catch (_) {
          // ignore load errors in UI
        }
      }
    })();
  }, [loading, user?.uid]);

  // Subscribe to recent session titles to keep sidebar in sync as single source of truth
  useEffect(() => {
    if (!loading && user?.uid) {
      try {
        const unsub = subscribeRecentSessionTitles(user.uid, RECENT_TAKE, (items) => {
          setConversations((prev) => {
            const map = new Map<string, Conversation>(prev.map((c) => [c.id, { ...c }]));
            let changed = false;
            for (const s of items) {
              const existing = map.get(s.id);
              if (existing) {
                if (existing.title !== s.title || existing.timestamp.getTime() !== s.updatedAt.getTime()) {
                  map.set(s.id, { ...existing, title: s.title, timestamp: s.updatedAt, datasetId: s.datasetId ?? existing.datasetId });
                  changed = true;
                }
              } else {
                map.set(s.id, { id: s.id, title: s.title, timestamp: s.updatedAt, messages: [], datasetId: s.datasetId });
                changed = true;
              }
            }
            if (!changed) return prev;
            const next = Array.from(map.values()).sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());
            return next.slice(0, RECENT_TAKE);
          });
        });
        return () => { try { unsub(); } catch {} };
      } catch {}
    }
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
      setConversations((prev) => [newConversation, ...prev].slice(0, RECENT_TAKE));
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

      const uploadMsgId = `${convId}-${Date.now()}-sys`;
      uploadMsgIdByConvRef.current[convId] = uploadMsgId;

      setConversations((prev) =>
        prev.map((c) =>
          c.id === convId
            ? {
                ...c,
                datasetId: resp.datasetId,
                messages: [
                  ...c.messages,
                  {
                    id: uploadMsgId,
                    role: "assistant",
                    kind: "text",
                    content:
                      "File uploaded and queued for preprocessing. You can now ask a question about your data.",
                    meta: { fileName: file.name, fileSize: formatBytes(file.size) },
                    timestamp: new Date(),
                  } as Message,
                ],
              }
            : c
        )
      );
      if (user?.uid) {
        updateSessionDataset(user.uid, convId, resp.datasetId).catch(() => {});
        try {
          datasetMetaSubsRef.current[convId]?.();
        } catch {}
        const unsub = subscribeDatasetMeta(user.uid, convId, resp.datasetId, (meta) => {
          const r = typeof meta?.rows === "number" ? meta.rows : undefined;
          const c = typeof meta?.columns === "number" ? meta.columns : undefined;
          if (r && c) {
            setConversations((prev) =>
              prev.map((sess) => {
                if (sess.id !== convId) return sess;
                const msgs = sess.messages.slice();
                const targetId = uploadMsgIdByConvRef.current[convId] || null;
                let idx = targetId ? msgs.findIndex((m) => m.id === targetId) : -1;
                if (idx === -1) {
                  for (let i = msgs.length - 1; i >= 0; i--) {
                    const m = msgs[i];
                    if (m.role === "assistant" && m.kind === "text") {
                      idx = i;
                      break;
                    }
                  }
                }
                if (idx >= 0) {
                  const m = msgs[idx] as Message;
                  msgs[idx] = {
                    ...(m as any),
                    meta: { ...(m as any).meta, rows: r, columns: c },
                  } as Message;
                }
                return { ...sess, messages: msgs };
              })
            );
            try {
              unsub();
            } catch {}
            delete datasetMetaSubsRef.current[convId];
            uploadMsgIdByConvRef.current[convId] = null;
          }
        });
        datasetMetaSubsRef.current[convId] = unsub;
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
    if ((profile?.messagesToday ?? 0) >= (profile?.quota ?? 50)) {
      alert("Daily quota reached. Please try again tomorrow or upgrade your plan.");
      return;
    }

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
              title:
                c.messages.length === 0
                  ? content.length > 50
                    ? content.slice(0, 50) + "..."
                    : content
                  : c.title,
            }
          : c
      )
    );
    if (user?.uid) {
      saveUserMessage(user.uid, convId, userMessage.id, content).catch(() => {});
    }

    const isCodeOnly = /\b(show|view|display|give|print)\b[^\n]*\bcode\b/i.test(content) || /\bcode only\b/i.test(content);

    if (summaryStreamTimerRef.current !== null) {
      window.clearInterval(summaryStreamTimerRef.current);
      summaryStreamTimerRef.current = null;
    }
    summaryStreamingRef.current = false;
    setIsTyping(true);
    codeInsertedByConvRef.current[convId] = false;
    codeMsgIdByConvRef.current[convId] = null;
    const ac = new AbortController();
    abortRef.current = ac;
    let placeholderId: string | null = null;
    if (!isCodeOnly) {
      placeholderId = `${convId}-${Date.now()}-ph`;
      placeholderIdRef.current = placeholderId;
      const placeholder: Message = {
        id: placeholderId,
        role: "assistant",
        kind: "status",
        content: "Analyzing...",
        timestamp: new Date(),
      };
      setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...c.messages, placeholder] } : c)));
    } else {
      placeholderIdRef.current = null;
    }

    const updatePlaceholder = (updater: (m: Extract<Message, { role: "assistant" }>) => Message): boolean => {
      let updated = false;
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== convId) return c;
          const idx = c.messages.findIndex((m) => m.id === placeholderId);
          if (idx === -1) return c;
          const nextMsgs = c.messages.slice();
          nextMsgs[idx] = updater(nextMsgs[idx] as Extract<Message, { role: "assistant" }>);
          updated = true;
          return { ...c, messages: nextMsgs };
        })
      );
      return updated;
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
          if (isCodeOnly) {
            if (ev.type === "code") {
              const existingId = codeMsgIdByConvRef.current[convId] || null;
              if (existingId) {
                setConversations((prev) =>
                  prev.map((c) => {
                    if (c.id !== convId) return c;
                    const msgs = c.messages.slice();
                    const idx = msgs.findIndex((m) => m.id === existingId);
                    if (idx >= 0) {
                      const m = msgs[idx] as any;
                      msgs[idx] = {
                        ...m,
                        code: ev.data.text,
                        language: ev.data.language || "python",
                        warnings: Array.isArray(ev.data.warnings) ? ev.data.warnings : undefined,
                        timestamp: new Date(),
                      } as any;
                    }
                    return { ...c, messages: msgs };
                  })
                );
              } else {
                const newId = `${convId}-${Date.now()}-code`;
                codeMsgIdByConvRef.current[convId] = newId;
                setConversations((prev) =>
                  prev.map((c) => {
                    if (c.id !== convId) return c;
                    const msgs = c.messages.slice();
                    const codeMsg: Message = {
                      id: newId,
                      role: "assistant",
                      timestamp: new Date(),
                      kind: "code",
                      code: ev.data.text,
                      language: ev.data.language || "python",
                      warnings: Array.isArray(ev.data.warnings) ? ev.data.warnings : undefined,
                    } as any;
                    msgs.push(codeMsg);
                    codeInsertedByConvRef.current[convId] = true;
                    return { ...c, messages: msgs };
                  })
                );
              }
              setIsTyping(false);
              try {
                abortRef.current?.abort();
              } catch {}
            }
            return;
          }

          if (ev.type === "validating") updatePlaceholder((m) => ({ ...m, kind: "status", content: "Validating input..." }));
          else if (ev.type === "generating_code") updatePlaceholder((m) => ({ ...m, kind: "status", content: "Generating analysis code..." }));
          else if (ev.type === "code") {
            const existingId = codeMsgIdByConvRef.current[convId] || null;
            if (existingId) {
              setConversations((prev) =>
                prev.map((c) => {
                  if (c.id !== convId) return c;
                  const msgs = c.messages.slice();
                  const idx = msgs.findIndex((m) => m.id === existingId);
                  if (idx >= 0) {
                    const m = msgs[idx] as any;
                    msgs[idx] = {
                      ...m,
                      code: ev.data.text,
                      language: ev.data.language || "python",
                      warnings: Array.isArray(ev.data.warnings) ? ev.data.warnings : undefined,
                      timestamp: new Date(),
                    } as any;
                  }
                  return { ...c, messages: msgs };
                })
              );
            } else {
              const newId = `${convId}-${Date.now()}-code`;
              codeMsgIdByConvRef.current[convId] = newId;
              setConversations((prev) =>
                prev.map((c) => {
                  if (c.id !== convId) return c;
                  const msgs = c.messages.slice();
                  const phIdx = msgs.findIndex((m) => m.id === placeholderIdRef.current);
                  const codeMsg: Message = {
                    id: newId,
                    role: "assistant",
                    timestamp: new Date(),
                    kind: "code",
                    code: ev.data.text,
                    language: ev.data.language || "python",
                    warnings: Array.isArray(ev.data.warnings) ? ev.data.warnings : undefined,
                  } as any;
                  if (phIdx >= 0) {
                    msgs.splice(phIdx, 0, codeMsg);
                  } else {
                    msgs.push(codeMsg);
                  }
                  codeInsertedByConvRef.current[convId] = true;
                  return { ...c, messages: msgs };
                })
              );
            }
          } else if (ev.type === "repairing") updatePlaceholder((m) => ({ ...m, kind: "status", content: "Repairing and retrying analysis..." }));
          else if (ev.type === "running_fast") updatePlaceholder((m) => ({ ...m, kind: "status", content: "Running analysis..." }));
          else if (ev.type === "summarizing") updatePlaceholder((m) => ({ ...m, kind: "status", content: "Summarizing results..." }));
          else if (ev.type === "persisting") updatePlaceholder((m) => ({ ...m, kind: "status", content: "Saving results..." }));
          else if (ev.type === "error") {
            updatePlaceholder((m) => ({ ...m, kind: "error", content: `Error: ${ev.data.message}` }));
            if (summaryStreamTimerRef.current !== null) {
              window.clearInterval(summaryStreamTimerRef.current);
              summaryStreamTimerRef.current = null;
            }
            summaryStreamingRef.current = false;
            setIsTyping(false);
          } else if (ev.type === "done") {
            const summaryText =
              typeof ev.data.summary === "string" && ev.data.summary.trim().length > 0
                ? ev.data.summary
                : "Analysis complete.";

            // Stash table and chart for staged reveal
            const rows = Array.isArray(ev.data.tableSample) ? ev.data.tableSample : [];
            const chartData = ev.data.chartData || null;

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

            if (summaryStreamTimerRef.current !== null) {
              window.clearInterval(summaryStreamTimerRef.current);
              summaryStreamTimerRef.current = null;
            }

            // Convert placeholder to text and stream words
            const placeholderReady = updatePlaceholder((m) => ({ ...m, kind: "text", content: "" }));
            if (placeholderReady) {
              summaryStreamingRef.current = true;
              const tokens = summaryText.split(/(\s+)/); // keep whitespace tokens
              let idx = 0;
              let wordsCounted = 0;
              let wordsTarget = 2; // alternate 2 and 3 words per tick

              const step = () => {
                let addedWordTokens = 0;
                while (idx < tokens.length && addedWordTokens < wordsTarget) {
                  const t = tokens[idx++];
                  if (t && /\S/.test(t)) {
                    addedWordTokens++;
                  }
                }
                // Include trailing whitespace after the last word added
                while (idx < tokens.length && tokens[idx] && !/\S/.test(tokens[idx])) {
                  // attach whitespace directly after the word bundle
                  idx++;
                }

                const nextText = tokens.slice(0, idx).join("");
                updatePlaceholder((m) => ({ ...m, kind: "text", content: nextText }));
                bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });

                // alternate 2 and 3
                wordsCounted++;
                wordsTarget = wordsTarget === 2 ? 3 : 2;

                if (idx >= tokens.length) {
                  if (summaryStreamTimerRef.current !== null) {
                    window.clearInterval(summaryStreamTimerRef.current);
                    summaryStreamTimerRef.current = null;
                  }
                  summaryStreamingRef.current = false;
                  setIsTyping(false);

                  // Reveal table (if any), then chart after a short delay
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
                  if (chartData && hasChartData(chartData)) {
                    window.setTimeout(() => {
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
                    }, 275);
                  }
                }
              };
              step();
              if (idx < tokens.length) {
                summaryStreamTimerRef.current = window.setInterval(step, 80);
              } else {
                summaryStreamingRef.current = false;
                setIsTyping(false);
              }
            } else {
              // Fallback: no placeholder present; set full text immediately and then reveal others
              summaryStreamingRef.current = false;
              updatePlaceholder((m) => ({ ...m, kind: "text", content: summaryText }));
              setIsTyping(false);
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
              if (chartData && hasChartData(chartData)) {
                window.setTimeout(() => {
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
                }, 275);
              }
            }

            if (user?.uid) {
              // Persist assistant summary message and increment usage
              saveAssistantMessage(user.uid, convId, `${convId}-${Date.now()}-asst`, summaryText).catch(() => {});
              incrementDailyUsage(user.uid).catch(() => {});
            }

            // Rename conversation once after first assistant reply if title is default or first-message truncated
            try {
              const convCurrent = conversations.find((c) => c.id === convId);
              const currentTitle = convCurrent?.title || "";
              const firstUserMsg = (convCurrent?.messages || []).find((m) => m.role === "user" && m.kind === "text") as any;
              const firstText = typeof firstUserMsg?.content === "string" ? firstUserMsg.content : content;
              const truncated = firstText ? (firstText.length > 50 ? firstText.slice(0, 50) + "..." : firstText) : "";
              const isDefault = currentTitle === "New conversation" || currentTitle === "New Conversation";
              const isTruncated = truncated && currentTitle === truncated;
              const renameAllowed = (isDefault || isTruncated) && !titleLockedRef.current[convId];
              if (renameAllowed) {
                const serverTitle = (ev.data as any)?.title;
                const nextTitle = typeof serverTitle === "string" && serverTitle.trim() ? serverTitle.trim() : generateTitleLocal(firstText, summaryText);
                if (nextTitle && user?.uid) {
                  titleLockedRef.current[convId] = true;
                  updateSessionTitle(user.uid, convId, nextTitle).catch(() => {});
                }
              }
            } catch {}
          }
        },
      });
    } catch (e: any) {
      if (summaryStreamTimerRef.current !== null) {
        window.clearInterval(summaryStreamTimerRef.current);
        summaryStreamTimerRef.current = null;
      }
      summaryStreamingRef.current = false;
      updatePlaceholder((m) => ({ ...m, kind: "error", content: `Connection error: ${e?.message || "stream interrupted"}` }));
      setIsTyping(false);
    } finally {
      abortRef.current = null;
      if (!summaryStreamingRef.current) {
        setIsTyping(false);
      }
    }
  };

  return (
    <div className="size-full flex bg-background">
      <ChatHeader sidebarOpen={sidebarOpen} />

      <ChatSidebar
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelectConversation={handleSelectConversation}
        onNewChat={handleNewChat}
        onDeleteConversation={handleDeleteConversation}
        userName={userName}
        userPlan={profile?.plan || "Free"}
        dailyLimit={dailyLimit}
        dailyUsed={dailyUsed}
        onSignOut={typeof signOut === 'function' ? () => signOut() : undefined}
      />

      <main
        className="flex-1 flex flex-col h-full transition-all duration-300 pt-14"
        style={{
          marginLeft: sidebarOpen ? "256px" : "64px",
        }}
      >
        <ScrollArea ref={scrollRef} className="flex-1">
          {activeConversation && activeConversation.messages.length > 0 ? (
            <div className="pb-32">
              {activeConversation.messages.map((message) => (
                <React.Fragment key={message.id}>
                  <ChatMessage
                    message={message}
                    userName={userName}
                    showCursor={
                      Boolean(
                        summaryStreamingRef.current &&
                        isTyping &&
                        message.role === "assistant" &&
                        message.kind === "text" &&
                        message.id === placeholderIdRef.current
                      )
                    }
                    showCancel={
                      isTyping &&
                      message.role === "assistant" &&
                      message.kind === "status" &&
                      message.id === placeholderIdRef.current
                    }
                    onCancel={handleCancel}
                  />
                </React.Fragment>
              ))}
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
