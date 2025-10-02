import { fetchEventSource } from "@microsoft/fetch-event-source";

export interface SignedUrlResponse {
  url: string;
  datasetId: string;
  storagePath: string;
}

export type ChatEvent =
  | { type: "ping"; ts: string }
  | { type: "received"; data: { sessionId: string; datasetId: string } }
  | { type: "validating" }
  | { type: "generating_code" }
  | { type: "running_fast" }
  | { type: "summarizing" }
  | { type: "persisting" }
  | { type: "error"; data: { code: string; message: string } }
  | {
      type: "done";
      data: {
        messageId: string;
        chartData?: any;
        tableSample?: any[];
        uris?: Record<string, string>;
        urisGs?: Record<string, string>;
        summary?: string;
      };
    };

export async function getSignedUploadUrl(params: {
  signUrl: string;
  idToken: string;
  sessionId: string;
  filename: string;
  size: number;
  type: string;
}): Promise<SignedUrlResponse> {
  const { signUrl, idToken, sessionId, filename, size, type } = params;
  const u = new URL(signUrl);
  u.searchParams.set("filename", filename);
  u.searchParams.set("size", String(size));
  u.searchParams.set("type", type);
  u.searchParams.set("sessionId", sessionId);

  const res = await fetch(u.toString(), {
    method: "GET",
    headers: {
      Authorization: `Bearer ${idToken}`,
    },
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`sign-upload-url failed ${res.status}: ${txt}`);
  }
  return (await res.json()) as SignedUrlResponse;
}

export async function putToSignedUrl(url: string, file: File) {
  const res = await fetch(url, {
    method: "PUT",
    headers: {
      "Content-Type": file.type || "application/octet-stream",
    },
    body: file,
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`PUT upload failed ${res.status}: ${txt}`);
  }
}

export async function streamChat(params: {
  chatUrl: string;
  idToken: string;
  sessionId: string;
  datasetId: string;
  question: string;
  signal?: AbortSignal;
  onEvent: (ev: ChatEvent) => void;
}) {
  const { chatUrl, idToken, sessionId, datasetId, question, signal, onEvent } = params;

  await fetchEventSource(chatUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${idToken}`,
    },
    body: JSON.stringify({ sessionId, datasetId, question }),
    signal,
    onmessage(msg) {
      if (!msg.data) return;
      try {
        const obj = JSON.parse(msg.data) as ChatEvent;
        onEvent(obj);
      } catch (_) {
        // ignore parse errors
      }
    },
    onerror(err) {
      throw err;
    },
    openWhenHidden: true,
  });
}
