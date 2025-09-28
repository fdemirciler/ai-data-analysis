import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { streamChat, requestSignedUploadUrl, uploadFileToSignedUrl } from "../services/api";
import {
	createSession,
	deleteAllSessions,
	deleteSession,
	listSessions,
	loadMessages,
	recordDataset,
	saveMessages,
	updateSession,
} from "../services/firestore";
import { Artifact, ChatMessage, ChatSession, MessageStatus, UploadState, UsageState } from "../types/chat";
import { useAuth } from "./AuthContext";

export type ConnectionState = "idle" | "connecting" | "streaming" | "error";

const DAILY_USAGE_LIMIT = 100;
const USAGE_STORAGE_KEY_PREFIX = "ada-usage::";

function currentDateKey() {
	return new Date().toISOString().slice(0, 10);
}

function loadUsage(uid: string): UsageState {
	const today = currentDateKey();
	try {
		const raw = localStorage.getItem(`${USAGE_STORAGE_KEY_PREFIX}${uid}`);
		if (!raw) {
			return { date: today, count: 0, limit: DAILY_USAGE_LIMIT };
		}
		const parsed = JSON.parse(raw) as UsageState;
		if (!parsed || parsed.date !== today) {
			return { date: today, count: 0, limit: DAILY_USAGE_LIMIT };
		}
		return { ...parsed, limit: parsed.limit ?? DAILY_USAGE_LIMIT };
	} catch (error) {
		console.warn("Failed to load usage", error);
		return { date: today, count: 0, limit: DAILY_USAGE_LIMIT };
	}
}

function persistUsage(uid: string, usage: UsageState) {
	try {
		localStorage.setItem(`${USAGE_STORAGE_KEY_PREFIX}${uid}`, JSON.stringify(usage));
	} catch (error) {
		console.warn("Failed to persist usage", error);
	}
}

interface SendMessagePayload {
	content: string;
	file?: File | null;
}

interface ChatContextValue {
	sessions: ChatSession[];
	activeSessionId: string | null;
	messages: ChatMessage[];
	upload: UploadState;
	connection: ConnectionState;
	isLoading: boolean;
	selectSession: (id: string) => Promise<void>;
	createNewSession: () => Promise<void>;
	deleteSessionById: (id: string) => Promise<void>;
	deleteAll: () => Promise<void>;
	sendMessage: (payload: SendMessagePayload) => Promise<void>;
	abortStream: () => void;
	usage: UsageState;
}

const ChatContext = createContext<ChatContextValue | undefined>(undefined);

export function ChatProvider({ children }: { children: React.ReactNode }) {
	const { user } = useAuth();
	const [sessions, setSessions] = useState<ChatSession[]>([]);
	const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
	const [messages, setMessages] = useState<ChatMessage[]>([]);
	const [upload, setUpload] = useState<UploadState>({ status: "idle" });
	const [connection, setConnection] = useState<ConnectionState>("idle");
	const [isLoading, setIsLoading] = useState(false);
	const [usage, setUsage] = useState<UsageState>({ date: currentDateKey(), count: 0, limit: DAILY_USAGE_LIMIT });
	const abortRef = useRef<() => void>();
	const assistantMessageIdRef = useRef<string | null>(null);

	const syncSessions = useCallback(async () => {
		if (!user) return [] as ChatSession[];
		const list = await listSessions(user.uid);
		setSessions(list);
		return list;
	}, [user]);

	const loadSessionMessages = useCallback(async (sessionId: string) => {
		if (!user) return [] as ChatMessage[];
		const loaded = await loadMessages(user.uid, sessionId);
		setMessages(loaded);
		return loaded;
	}, [user]);

	useEffect(() => {
		if (!user) {
			setSessions([]);
			setActiveSessionId(null);
			setMessages([]);
			setUsage({ date: currentDateKey(), count: 0, limit: DAILY_USAGE_LIMIT });
			return;
		}

		(async () => {
			const list = await syncSessions();
			if (list.length === 0) {
				setActiveSessionId(null);
				setMessages([]);
				return;
			}
			const initialId = list[0].id;
			setActiveSessionId(initialId);
			await loadSessionMessages(initialId);
		})();

		const loadedUsage = user ? loadUsage(user.uid) : { date: currentDateKey(), count: 0, limit: DAILY_USAGE_LIMIT };
		setUsage(loadedUsage);
	}, [loadSessionMessages, syncSessions, user]);

	const setAndPersistMessages = useCallback(
		(sessionId: string, updater: (prev: ChatMessage[]) => ChatMessage[]) => {
			setMessages((prev) => {
				const next = updater(prev);
				if (user) {
					void saveMessages(user.uid, sessionId, next);
				}
			const activity = new Date().toISOString();
			setSessions((sessionsPrev) => {
				const updated = sessionsPrev.map((session) =>
					session.id === sessionId
						? {
							...session,
							messageCount: next.length,
							lastActivityAt: activity,
							updatedAt: activity,
						}
						: session,
				);
				return updated.sort((a, b) => (a.lastActivityAt < b.lastActivityAt ? 1 : -1));
			});
				return next;
			});
		},
		[user],
	);

	const ensureSessionId = useCallback(async () => {
		if (!user) throw new Error("Not authenticated");
		if (activeSessionId) return activeSessionId;
		const session = await createSession(user.uid, "New analysis");
		setSessions((prev) => [session, ...prev]);
		setActiveSessionId(session.id);
		setMessages([]);
		await saveMessages(user.uid, session.id, []);
		return session.id;
	}, [activeSessionId, user]);

	const selectSession = useCallback(async (id: string) => {
		setActiveSessionId(id);
		await loadSessionMessages(id);
	}, [loadSessionMessages]);

	const createNewSession = useCallback(async () => {
		if (!user) return;
		const session = await createSession(user.uid, "New analysis");
		setSessions((prev) => [session, ...prev]);
		setActiveSessionId(session.id);
		setMessages([]);
		await saveMessages(user.uid, session.id, []);
	}, [user]);

	const deleteSessionById = useCallback(async (id: string) => {
		if (!user) return;
		abortRef.current?.();
		await deleteSession(user.uid, id);
		const list = await syncSessions();
		const nextId = list[0]?.id ?? null;
		setActiveSessionId(nextId);
		if (nextId) {
			await loadSessionMessages(nextId);
		} else {
			setMessages([]);
		}
	}, [loadSessionMessages, syncSessions, user]);

	const deleteAll = useCallback(async () => {
		if (!user) return;
		abortRef.current?.();
		await deleteAllSessions(user.uid);
		setSessions([]);
		setActiveSessionId(null);
		setMessages([]);
	}, [user]);

	const updateSessionTitle = useCallback(
		(sessionId: string, title: string) => {
			if (!user) return;
			setSessions((prev) =>
				prev.map((session) =>
					session.id === sessionId
						? { ...session, title, updatedAt: new Date().toISOString(), lastActivityAt: new Date().toISOString() }
						: session,
				),
			);
			void updateSession(user.uid, sessionId, { title, lastActivityAt: new Date().toISOString() });
		},
		[user],
	);

	const abortStream = useCallback(() => {
		abortRef.current?.();
		abortRef.current = undefined;
		assistantMessageIdRef.current = null;
		setConnection("idle");
		setIsLoading(false);
	}, []);

	const handleStreamEvent = useCallback(
		(sessionId: string, event: ReturnType<typeof mapStreamEvent>) => {
			if (!event || !assistantMessageIdRef.current) return;
			if (event.kind === "status") {
				setConnection(event.state);
				return;
			}

			if (event.kind === "update") {
				setAndPersistMessages(sessionId, (prev) =>
					prev.map((message) => {
						if (message.id !== assistantMessageIdRef.current) return message;
						return {
							...message,
							content: event.content ?? message.content,
							code: event.code ?? message.code,
							table: event.table ?? message.table,
							chart: event.chart ?? message.chart,
							artifacts: event.artifacts ?? message.artifacts,
							status: event.status ?? message.status,
							isStreaming: event.status === "streaming",
						};
					}),
				);
				return;
			}

			if (event.kind === "complete") {
				setAndPersistMessages(sessionId, (prev) =>
					prev.map((message) =>
						message.id === assistantMessageIdRef.current
							? { ...message, status: "completed", isStreaming: false }
							: message,
					),
				);
				setUpload((prev) => (prev.status === "uploaded" ? { status: "idle" } : prev));
				setConnection("idle");
				setIsLoading(false);
				assistantMessageIdRef.current = null;
				abortRef.current = undefined;
			}
		},
		[setAndPersistMessages],
	);

	const incrementUsage = useCallback(() => {
		if (!user) return;
		setUsage((prev) => {
			const today = currentDateKey();
			const base = prev.date === today ? prev : { date: today, count: 0, limit: prev.limit };
			const nextCount = Math.min(base.count + 1, base.limit);
			const next = { ...base, count: nextCount };
			persistUsage(user.uid, next);
			return next;
		});
	}, [user]);

	const sendMessage = useCallback(
		async ({ content, file }: SendMessagePayload) => {
			if (!user) return;
			if (!content.trim() && !file) return;

			const sessionId = await ensureSessionId();
			const timestamp = new Date().toISOString();
			const isFirstMessage = messages.length === 0 || sessionId !== activeSessionId;

			const userMessage: ChatMessage = {
				id: crypto.randomUUID(),
				role: "user",
				content: file ? `${content}\n\n[Uploaded: ${file.name}]` : content,
				timestamp,
				status: "completed",
			};

			const assistantMessage: ChatMessage = {
				id: crypto.randomUUID(),
				role: "assistant",
				content: "",
				timestamp,
				status: "streaming",
				isStreaming: true,
			};

			assistantMessageIdRef.current = assistantMessage.id;
			setIsLoading(true);
			setConnection("connecting");

			setAndPersistMessages(sessionId, (prev) => [...prev, userMessage, assistantMessage]);
			incrementUsage();

			if (isFirstMessage) {
				const preview = content.trim().slice(0, 60) || "New analysis";
				updateSessionTitle(sessionId, preview);
			}

			let datasetId: string | undefined;
			try {
				if (file) {
					setUpload({ status: "uploading", progress: 0 });
					const signed = await requestSignedUploadUrl({
						filename: file.name,
						size: file.size,
						mime: file.type || "application/octet-stream",
						uid: user.uid,
						sid: sessionId,
					});
					datasetId = signed.datasetId;
					await uploadFileToSignedUrl(signed.url, file, (ratio) => {
						setUpload({ status: "uploading", progress: ratio, datasetId });
					});
					setUpload({ status: "uploaded", progress: 1, datasetId });
					await recordDataset(user.uid, sessionId, datasetId);
					setSessions((prev) =>
						prev.map((session) =>
							session.id === sessionId
								? {
									...session,
									activeDatasetIds: session.activeDatasetIds.includes(datasetId!)
										? session.activeDatasetIds
										: [datasetId!, ...session.activeDatasetIds].slice(0, 10),
								}
								: session,
						),
					);
				}
			} catch (error) {
				console.error(error);
				setUpload({ status: "error", message: (error as Error).message });
				setAndPersistMessages(sessionId, (prev) =>
					prev.map((message) =>
						message.id === assistantMessage.id
							? { ...message, status: "error", content: "Upload failed. Please try again.", isStreaming: false }
							: message,
					),
				);
				setIsLoading(false);
				setConnection("error");
				assistantMessageIdRef.current = null;
				return;
			}

			setConnection("streaming");

			abortRef.current = streamChat({
				sessionId,
				message: content,
				datasetId,
				uid: user.uid,
				sid: sessionId,
				onEvent: (raw) => {
					const mapped = mapStreamEvent(raw);
					if (mapped?.kind === "error") {
						setAndPersistMessages(sessionId, (prev) =>
							prev.map((msg) =>
								msg.id === assistantMessage.id
									? {
										...msg,
										status: "error",
										isStreaming: false,
										content: mapped.message ?? msg.content,
									}
									: msg,
								),
						);
						setConnection("error");
						setIsLoading(false);
						assistantMessageIdRef.current = null;
						abortRef.current = undefined;
						return;
					}
					handleStreamEvent(sessionId, mapped);
				},
				onError: (error) => {
					console.error(error);
					setAndPersistMessages(sessionId, (prev) =>
						prev.map((msg) =>
							msg.id === assistantMessage.id
								? { ...msg, status: "error", isStreaming: false, content: "Connection error. Please retry." }
								: msg,
						),
					);
					setConnection("error");
					setIsLoading(false);
				},
			});
		},
		[activeSessionId, ensureSessionId, handleStreamEvent, messages.length, setAndPersistMessages, updateSessionTitle, user],
	);

	const value = useMemo<ChatContextValue>(() => ({
		sessions,
		activeSessionId,
		messages,
		upload,
		connection,
		isLoading,
		selectSession,
		createNewSession,
		deleteSessionById,
		deleteAll,
		sendMessage,
		abortStream,
		usage,
	}), [
		sessions,
		activeSessionId,
		messages,
		upload,
		connection,
		isLoading,
		selectSession,
		createNewSession,
		deleteSessionById,
		deleteAll,
		sendMessage,
		abortStream,
		usage,
	]);

	return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat() {
	const ctx = useContext(ChatContext);
	if (!ctx) {
		throw new Error("useChat must be used within ChatProvider");
	}
	return ctx;
}

function mapStreamEvent(event: { type: string; data?: any; raw?: string } | undefined):
	| { kind: "status"; state: ConnectionState }
	| {
		kind: "update";
		content?: string;
		code?: string;
		table?: ChatMessage["table"];
		chart?: ChatMessage["chart"];
		artifacts?: Artifact[];
		status?: MessageStatus;
	}
	| { kind: "complete" }
	| { kind: "error"; message?: string }
	| undefined {
	if (!event) return undefined;
	switch (event.type) {
		case "analysis_start":
		case "received":
		case "classifying":
		case "validating":
		case "running_fast":
		case "summarizing":
		case "persisting":
			return { kind: "status", state: "streaming" };
		case "partial":
			return {
				kind: "update",
				content: event.data?.text ?? "",
				status: "streaming",
			};
		case "result":
			return {
				kind: "update",
				content: event.data?.text,
				code: event.data?.code,
				table: event.data?.table,
				chart: event.data?.chart,
				artifacts: event.data?.artifacts,
				status: "streaming",
			};
		case "done":
			return { kind: "complete" };
		case "error":
			return { kind: "error", message: event.data?.message ?? "Request failed." };
		default:
			return undefined;
	}
}
