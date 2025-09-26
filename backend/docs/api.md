# Backend API (Draft v1)

This document describes the backend endpoints and SSE event contract. All endpoints are in region `europe-west4`.

## Authentication

- For simplicity in the draft, examples omit auth. In production, attach a user identity (e.g., Firebase Auth ID) and pass `uid` and `sid` (session ID) via headers or cookies.
- Example headers (subject to change):
  - `X-User-Id: <uid>`
  - `X-Session-Id: <sid>`

---

## 1) GET `/api/sign-upload-url`

Issue a signed URL for direct browser PUT to GCS.

Query parameters:
- `filename`: string (required)
- `size`: integer bytes (required, ≤ 20MB)
- `type`: mime type, e.g., `text/csv` or `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (required)

Headers:
- `X-User-Id`: uid
- `X-Session-Id`: sid

Response 200 JSON:
```json
{
  "url": "https://storage.googleapis.com/...",
  "datasetId": "<uuid>",
  "storagePath": "users/<uid>/sessions/<sid>/datasets/<datasetId>/raw/input.csv"
}
```

Notes:
- Signed URL method: PUT
- Required headers when uploading: `Content-Type: <type>`
- CORS: configured on bucket `ai-data-analyser-files` for `http://localhost:3000` (prod domain added later)

---

## 2) POST `/api/chat` (SSE)

Start an analysis step; returns a Server-Sent Events stream.

Request JSON:
```json
{
  "sessionId": "<sid>",
  "datasetId": "<datasetId>",
  "message": "Find trends in revenue by region"
}
```

SSE events (examples):
```json
{"type":"received"}
{"type":"classifying","data":{"message":"Analyzing query intent..."}}
{"type":"validating"}
{"type":"running_fast"}
{"type":"summarizing"}
{"type":"persisting"}
{"type":"done","data":{"resultRef":"gs://ai-data-analyser-files/users/.../results/<messageId>/"}}
{"type":"ping"}
```

Behavior:
- Hour/day quotas enforced.
- If `runtime_flags.allowComplex=false`, COMPLEX requests fall back to templates.
- Heartbeat: JSON `{ "type": "ping" }` every ~20–25 seconds.

---

## 3) POST `/api/session/:id/close`

Immediately purge all artifacts for a session and delete Firestore docs.

Response 202 JSON:
```json
{"status":"accepted"}
```

Notes:
- GCS prefix-scope TTL (1 day on `users/`) remains as safety net.

---

## 4) Eventarc → Cloud Run `/eventarc` (Preprocess)

HTTP target for GCS-object-finalize events. Expects CloudEvent-like body with at least:
```json
{
  "data": {
    "bucket": "ai-data-analyser-files",
    "name": "users/<uid>/sessions/<sid>/datasets/<datasetId>/raw/input.csv"
  },
  "id": "...",
  "source": "...",
  "type": "google.cloud.storage.object.v1.finalized",
  "time": "..."
}
```

Response:
- `204 No Content` on success/ignored events.

Processing:
- Download raw → run pipeline → write `cleaned.parquet`, `payload.json`, `cleaning_report.json` → update Firestore dataset doc.
