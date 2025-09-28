export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "https://mock-backend.local";
export const SIGN_UPLOAD_ENDPOINT = "/api/sign-upload-url";
export const CHAT_ENDPOINT = "/api/chat";
export const SESSION_CLOSE_ENDPOINT = (sessionId: string) => `/api/session/${sessionId}/close`;

export const FIRESTORE_NAMESPACE = "ai-data-analyser";

export const SSE_RETRY_MS = 2000;
