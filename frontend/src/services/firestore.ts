import { db } from "../lib/firebase";
import {
  collection,
  doc,
  setDoc,
  updateDoc,
  getDocs,
  orderBy,
  limit as qlimit,
  query,
  onSnapshot,
} from "firebase/firestore";
import type { Message } from "../components/ChatMessage";

export async function ensureSession(uid: string, sid: string, title: string) {
  const ref = doc(collection(db, "users", uid, "sessions"), sid);
  const now = new Date();
  await setDoc(
    ref,
    { title, createdAt: now, updatedAt: now },
    { merge: true }
  );
}

export function subscribeDatasetMeta(
  uid: string,
  sid: string,
  datasetId: string,
  cb: (meta: { rows?: number; columns?: number }) => void
): () => void {
  const ref = doc(collection(db, "users", uid, "sessions", sid, "datasets"), datasetId);
  const unsub = onSnapshot(ref, (snap) => {
    const d = (snap.data() as any) || {};
    cb({ rows: d?.rows, columns: d?.columns });
  });
  return unsub;
}

export async function updateSessionDataset(uid: string, sid: string, datasetId: string) {
  const ref = doc(collection(db, "users", uid, "sessions"), sid);
  const now = new Date();
  await updateDoc(ref, { datasetId, updatedAt: now });
}

export async function saveUserMessage(uid: string, sid: string, messageId: string, content: string) {
  const msgRef = doc(collection(db, "users", uid, "sessions", sid, "messages"), messageId);
  const now = new Date();
  await setDoc(msgRef, { role: "user", content, createdAt: now }, { merge: true });
}

function toDate(x: any): Date {
  // Firestore Timestamp compatibility
  if (x && typeof x.toDate === "function") return x.toDate();
  if (typeof x === "string" || typeof x === "number") return new Date(x);
  return new Date();
}

export interface ConversationLoaded {
  id: string;
  title: string;
  timestamp: Date;
  messages: Message[];
  datasetId?: string;
}

export async function getRecentSessionsWithMessages(uid: string, take: number): Promise<ConversationLoaded[]> {
  const sessCol = collection(db, "users", uid, "sessions");
  const q = query(sessCol, orderBy("updatedAt", "desc"), qlimit(take));
  const snap = await getDocs(q);

  const convs: ConversationLoaded[] = [];
  for (const s of snap.docs) {
    const sd = s.data() as any;
    const sessId = s.id;
    const title = sd?.title || "Untitled";
    const datasetId = sd?.datasetId as string | undefined;
    const timestamp = toDate(sd?.updatedAt || sd?.createdAt);

    // Load messages (ascending)
    const msgCol = collection(db, "users", uid, "sessions", sessId, "messages");
    const mQ = query(msgCol, orderBy("createdAt", "asc"), qlimit(200));
    const mSnap = await getDocs(mQ);
    const messages: Message[] = [];
    for (const m of mSnap.docs) {
      const md = m.data() as any;
      const role = (md?.role === "assistant" ? "assistant" : "user") as "assistant" | "user";
      const content = typeof md?.content === "string" ? md.content : "";
      messages.push({ id: m.id, role, kind: "text", content, timestamp: toDate(md?.createdAt) });
    }

    convs.push({ id: sessId, title, timestamp, messages, datasetId });
  }
  return convs;
}
