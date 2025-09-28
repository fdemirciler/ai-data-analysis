import { ChatMessage, ChatSession, SessionPersistence } from "../types/chat";

const STORAGE_KEY_PREFIX = "ada-chat::";

function storageKey(uid: string) {
	return `${STORAGE_KEY_PREFIX}${uid}`;
}

function load(uid: string): SessionPersistence {
	try {
		const raw = localStorage.getItem(storageKey(uid));
		if (!raw) return { sessions: [], messagesBySession: {} };
		const parsed = JSON.parse(raw) as SessionPersistence;
		return {
			sessions: parsed.sessions ?? [],
			messagesBySession: parsed.messagesBySession ?? {},
		};
	} catch (error) {
		console.warn("Failed to load sessions", error);
		return { sessions: [], messagesBySession: {} };
	}
}

function persist(uid: string, data: SessionPersistence) {
	localStorage.setItem(storageKey(uid), JSON.stringify(data));
}

export async function listSessions(uid: string): Promise<ChatSession[]> {
	return load(uid).sessions.sort((a, b) => (a.lastActivityAt < b.lastActivityAt ? 1 : -1));
}

export async function createSession(uid: string, title: string): Promise<ChatSession> {
	const data = load(uid);
	const now = new Date().toISOString();
	const session: ChatSession = {
		id: crypto.randomUUID(),
		title,
		createdAt: now,
		updatedAt: now,
		lastActivityAt: now,
		messageCount: 0,
		activeDatasetIds: [],
	};
	data.sessions = [session, ...data.sessions];
	data.messagesBySession[session.id] = [];
	persist(uid, data);
	return session;
}

export async function saveMessages(uid: string, sessionId: string, messages: ChatMessage[]) {
	const data = load(uid);
	data.messagesBySession[sessionId] = messages;
	const session = data.sessions.find((item) => item.id === sessionId);
	if (session) {
		session.messageCount = messages.length;
		session.lastActivityAt = messages[messages.length - 1]?.timestamp ?? session.lastActivityAt;
		session.updatedAt = new Date().toISOString();
	}
	persist(uid, data);
}

export async function loadMessages(uid: string, sessionId: string): Promise<ChatMessage[]> {
	const data = load(uid);
	return data.messagesBySession[sessionId] ?? [];
}

export async function updateSession(uid: string, sessionId: string, patch: Partial<ChatSession>) {
	const data = load(uid);
	data.sessions = data.sessions.map((session) => (session.id === sessionId ? { ...session, ...patch, updatedAt: new Date().toISOString() } : session));
	persist(uid, data);
}

export async function recordDataset(uid: string, sessionId: string, datasetId: string) {
	const data = load(uid);
	data.sessions = data.sessions.map((session) => {
		if (session.id !== sessionId) return session;
		const activeDatasetIds = session.activeDatasetIds.includes(datasetId)
			? session.activeDatasetIds
			: [datasetId, ...session.activeDatasetIds].slice(0, 10);
		return { ...session, activeDatasetIds, updatedAt: new Date().toISOString(), lastActivityAt: new Date().toISOString() };
	});
	persist(uid, data);
}

export async function deleteSession(uid: string, sessionId: string) {
	const data = load(uid);
	data.sessions = data.sessions.filter((session) => session.id !== sessionId);
	delete data.messagesBySession[sessionId];
	persist(uid, data);
}

export async function deleteAllSessions(uid: string) {
	persist(uid, { sessions: [], messagesBySession: {} });
}
