import { API_BASE_URL, CHAT_ENDPOINT, SESSION_CLOSE_ENDPOINT, SIGN_UPLOAD_ENDPOINT } from "../lib/config";

export interface SignedUploadResponse {
	datasetId: string;
	storagePath: string;
	url: string;
}

export interface StreamEvent<T = unknown> {
	type: string;
	data?: T;
	raw?: string;
}

export interface StreamChatParams {
	sessionId: string;
	message: string;
	datasetId?: string;
	uid: string;
	sid: string;
	onEvent: (event: StreamEvent) => void;
	onError?: (error: Error) => void;
	signal?: AbortSignal;
}

export async function requestSignedUploadUrl(params: {
	filename: string;
	size: number;
	mime: string;
	uid: string;
	sid: string;
}): Promise<SignedUploadResponse> {
	const search = new URLSearchParams({
		filename: params.filename,
		size: String(params.size),
		type: params.mime,
	});

	const resp = await fetch(`${API_BASE_URL}${SIGN_UPLOAD_ENDPOINT}?${search.toString()}`, {
		headers: {
			"X-User-Id": params.uid,
			"X-Session-Id": params.sid,
		},
	});

	if (!resp.ok) {
		throw new Error(`Failed to request signed upload URL (${resp.status})`);
	}

	return resp.json();
}

export function uploadFileToSignedUrl(url: string, file: File, onProgress?: (ratio: number) => void) {
	return new Promise<void>((resolve, reject) => {
		const xhr = new XMLHttpRequest();
		xhr.open("PUT", url);
		xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");

		xhr.upload.onprogress = (event) => {
			if (event.lengthComputable) {
				onProgress?.(event.loaded / event.total);
			}
		};

		xhr.onload = () => {
			if (xhr.status >= 200 && xhr.status < 300) {
				resolve();
			} else {
				reject(new Error(`Upload failed (${xhr.status})`));
			}
		};

		xhr.onerror = () => {
			reject(new Error("Upload failed"));
		};

		xhr.onabort = () => {
			reject(new Error("Upload aborted"));
		};

		xhr.send(file);
	});
}

export function streamChat(params: StreamChatParams) {
	const controller = new AbortController();

	if (params.signal) {
		if (params.signal.aborted) {
			controller.abort();
		} else {
			params.signal.addEventListener("abort", () => controller.abort(), { once: true });
		}
	}

	(async () => {
		try {
			await pumpEvents({ ...params, signal: controller.signal });
		} catch (error) {
			if (error instanceof Error && error.name === "AbortError") {
				return;
			}
			params.onError?.(error as Error);
		}
	})();

	return () => controller.abort();
}

async function pumpEvents(params: StreamChatParams) {
	const response = await fetch(`${API_BASE_URL}${CHAT_ENDPOINT}`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Accept: "text/event-stream",
			"X-User-Id": params.uid,
			"X-Session-Id": params.sid,
		},
		body: JSON.stringify({
			sessionId: params.sessionId,
			datasetId: params.datasetId,
			message: params.message,
		}),
		signal: params.signal,
	});

	if (!response.ok || !response.body) {
		throw new Error(`Failed to open chat stream (${response.status})`);
	}

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";

	const retryTimeouts: Array<ReturnType<typeof setTimeout>> = [];

	const clearRetries = () => {
		retryTimeouts.forEach(clearTimeout);
		retryTimeouts.length = 0;
	};

	try {
		while (true) {
			const { value, done } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });
			buffer = processBuffer(buffer, params.onEvent, retryTimeouts);
		}
	} finally {
		clearRetries();
		reader.releaseLock();
	}
}

function processBuffer(buffer: string, onEvent: (event: StreamEvent) => void, retryTimeouts: Array<ReturnType<typeof setTimeout>>) {
	let cursor = buffer.indexOf("\n\n");
	let consumed = 0;

	while (cursor !== -1) {
		const rawEvent = buffer.slice(consumed, cursor);
		const lines = rawEvent.split("\n");
		let type = "message";
		const dataLines: string[] = [];

		for (const line of lines) {
			const trimmed = line.trim();
			if (!trimmed) continue;
			if (trimmed.startsWith("event:")) {
				type = trimmed.slice(6).trim();
			} else if (trimmed.startsWith("data:")) {
				dataLines.push(trimmed.slice(5).trim());
			} else if (trimmed.startsWith("retry:")) {
				const retryMs = Number(trimmed.slice(6).trim());
				if (!Number.isNaN(retryMs)) {
					retryTimeouts.push(setTimeout(() => {
						onEvent({ type: "retry", data: retryMs });
					}, retryMs));
				}
			}
		}

		let parsed: unknown;
		if (dataLines.length > 0) {
			const payload = dataLines.join("\n");
			try {
				parsed = payload ? JSON.parse(payload) : undefined;
			} catch (error) {
				onEvent({ type, raw: payload });
				consumed = cursor + 2;
				cursor = buffer.indexOf("\n\n", consumed);
				continue;
			}
		}

		onEvent({ type, data: parsed });
		consumed = cursor + 2;
		cursor = buffer.indexOf("\n\n", consumed);
	}

	return buffer.slice(consumed);
}

export async function closeSession(params: { sessionId: string; uid: string; sid: string }) {
	const resp = await fetch(`${API_BASE_URL}${SESSION_CLOSE_ENDPOINT(params.sessionId)}`, {
		method: "POST",
		headers: {
			"X-User-Id": params.uid,
			"X-Session-Id": params.sid,
		},
	});

	if (!resp.ok) {
		throw new Error(`Failed to close session (${resp.status})`);
	}

	return resp.json().catch(() => ({}));
}
