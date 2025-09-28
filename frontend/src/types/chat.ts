export type MessageRole = "user" | "assistant";

export interface Artifact {
	type: string;
	url: string;
	filename: string;
}

export interface TableRow {
	[key: string]: unknown;
}

export interface ChartPayload {
	type?: string;
	data?: unknown;
	options?: unknown;
}

export interface ChatMessage {
	id: string;
	role: MessageRole;
	content: string;
	timestamp: string;
	code?: string;
	chart?: ChartPayload;
	table?: TableRow[];
	artifacts?: Artifact[];
	isStreaming?: boolean;
	status?: MessageStatus;
}

export type MessageStatus =
	| "pending"
	| "streaming"
	| "completed"
	| "error";

export interface ChatSession {
	id: string;
	title: string;
	createdAt: string;
	updatedAt: string;
	lastActivityAt: string;
	messageCount: number;
	activeDatasetIds: string[];
}

export interface UploadState {
	status: "idle" | "uploading" | "uploaded" | "error";
	progress?: number;
	datasetId?: string;
	message?: string;
}

export interface UserIdentity {
	uid: string;
	name: string;
	email: string;
}

export interface SessionPersistence {
	sessions: ChatSession[];
	messagesBySession: Record<string, ChatMessage[]>;
}

export interface UsageState {
	date: string;
	count: number;
	limit: number;
}
