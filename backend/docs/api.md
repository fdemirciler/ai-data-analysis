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

Start an analysis step; streams progress and results. LLM (Gemini 2.5 Flash) generates
Python that operates on the dataset with Pandas/Numpy. Code is validated and executed
in a sandboxed child process with a hard 60s timeout.

Request JSON:
```json
{
  "uid": "<uid>",
  "sessionId": "<sid>",
  "datasetId": "<datasetId>",
  "question": "Find trends in revenue by region"
}
```

Headers:
- `X-User-Id: <uid>` (optional if provided in body)
- `X-Session-Id: <sid>` (optional if provided in body)

SSE events (examples):
```json
{"type":"received","data":{"sessionId":"<sid>","datasetId":"<datasetId>"}}
{"type":"validating"}
{"type":"generating_code"}
{"type":"running_fast"}
{"type":"summarizing"}
{"type":"persisting"}
{"type":"done","data":{
  "messageId":"<uuid>",
  "chartData": {"kind":"bar","labels":["A","B"],"series":[{"label":"Value","data":[1,2]}]},
  "tableSample": [{"category":"A","value":1},{"category":"B","value":2}],
  "uris":{
    "table":"gs://ai-data-analyser-files/users/.../results/<messageId>/table.json",
    "metrics":"gs://.../metrics.json",
    "chartData":"gs://.../chart_data.json",
    "summary":"gs://.../summary.json"
  }
}}
{"type":"ping"}
```

Chart data schema (backend → frontend/Chart.js):
```json
{
  "kind": "bar" | "line" | "pie",
  "labels": ["x1", "x2", "x3"],
  "series": [
    { "label": "Series A", "data": [1, 2, 3] }
  ],
  "options": { /* optional hints */ }
}
```

Behavior:
- Heartbeat: `{ "type": "ping" }` about every 20–25 seconds.
- Hard timeout: 60s. On expiry emits `{"type":"error","data":{"code":"TIMEOUT_HARD"}}`.
- Soft timeout: currently logs only (no partial-return yet).

Error codes (non-exhaustive):
- `MISSING_PARQUET` – cleaned.parquet not found
- `DOWNLOAD_FAILED` – failed to download dataset artifacts
- `CODEGEN_FAILED` – LLM code generation failure
- `CODE_VALIDATION_FAILED` – AST/allowlist validation failure
- `EXEC_FAILED` – sandboxed execution failed (stderr included)
- `BAD_RESULT` – sandbox output not valid JSON/shape
- `PERSIST_FAILED` – failed to write results to GCS

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
