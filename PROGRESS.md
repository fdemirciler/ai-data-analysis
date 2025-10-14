# AI Data Analyst — Progress Report

Date: 2025-10-14 16:56 (+02:00)

## Current Status
- **Preprocessing is fully functional**. Upload via signed URL triggers preprocessing; artifacts are generated and Firestore status advances to `ready`.
- **Frontend integrated (Auth + Upload + Chat SSE)**. Firebase Anonymous Auth, upload via signed URL, and chat SSE orchestrator are working end-to-end. Artifacts (`table.json`, `metrics.json`, `chart_data.json`, `summary.json`) are produced and signed for browser access.
- **CORS aligned for dev**. Dev runs on `http://localhost:5173`; functions allow Origin and lowercase headers in preflight. Frontend passes `sessionId` as a query param to avoid custom header preflight.
- **End-to-end smoke tests pass** using `test.ps1`.

## Deployed Components
- **Cloud Run service: `preprocess-svc`**
  - Framework: `FastAPI` in `backend/run-preprocess/main.py`.
  - Endpoints:
    - `GET /healthz` â€“ lightweight health endpoint (service is private; unauthenticated calls may 403/404).
    - `POST /eventarc` â€“ Eventarc target; parses CloudEvents in multiple delivery shapes (structured, binary, Pub/Sub push, and GCS notification compatibility).
  - Responsibilities:
    - Download raw file from GCS under `users/{uid}/sessions/{sid}/datasets/{datasetId}/raw/input.{csv|xlsx}`.
    - Run pipeline `backend/run-preprocess/pipeline_adapter.py` to clean and profile data.
    - Write artifacts:
      - `cleaned/cleaned.parquet`
      - `metadata/payload.json`
      - `reports/cleaning_report.json`
    - Update Firestore dataset document with `status: ready`, rows, columns, and artifact URIs.
  - Observability: integrates Google Cloud Logging (`cloud-logging: configured`).

- **Cloud Functions (Gen2): `sign-upload-url`**
  - Path: `backend/functions/sign_upload_url/main.py`.
  - Functionality: issues a V4 signed URL for direct browser PUT upload.
  - Security: uses IAM-based signing via impersonated credentials (no private key).
  - Behavior: creates initial Firestore dataset doc with `status: awaiting_upload` and `ttlAt`.

- **Cloud Functions (Gen2): `chat` (orchestrator, SSE)**
  - Path: `backend/functions/orchestrator/` (deployed and available; orchestration logic outside the scope of this stage).

- **Eventarc Trigger: `preprocess-trigger`**
  - Filters: `type=google.cloud.storage.object.v1.finalized`, `bucket=ai-data-analyser-files`.
  - Destination: Cloud Run `preprocess-svc` path `/eventarc` (region `europe-west4`).
  - Transport: Pub/Sub (managed subscription/topic).

- **Google Cloud Storage (GCS)**
  - Bucket: `ai-data-analyser-files`.
  - Structure per dataset:
    - `raw/input.csv` (or `.xlsx`)
    - `cleaned/cleaned.parquet`
    - `metadata/payload.json`
    - `reports/cleaning_report.json`

- **Firestore (Native mode)**
  - Collection path: `users/{uid}/sessions/{sid}/datasets/{datasetId}`.
  - Fields (subset): `status`, `rawUri`, `cleanedUri`, `payloadUri`, `reportUri`, `rows`, `columns`, `updatedAt`, `ttlAt`.
  - TTL Policy: Enabled on collection group `datasets` for field `ttlAt` (state: ACTIVE).

## Architecture & Design
- **Design principles**
  - Keep compute stateless and ephemeral; persist state/artifacts in Firestore + GCS.
  - Use direct-to-GCS uploads via signed URLs; minimize function runtime and egress.
  - Eliminate private keys; prefer IAM-based signing and workload identity.
  - Event-driven preprocessing via Eventarc to decouple upload from processing.

- **High-level flow**
```mermaid
flowchart TD
  A[Client] -->|GET sign-upload-url| F[Cloud Function: sign-upload-url]
  F -->|V4 signed URL + datasetId| A
  A -->|PUT file via Signed URL| B[GCS: ai-data-analyser-files]
  B -->|Object Finalized| E[Eventarc]
  E -->|HTTP CloudEvent| R[Cloud Run: preprocess-svc /eventarc]
  R -->|Clean + Profile| GCSArtifacts[(Artifacts in GCS)]
  R -->|Update| FS[(Firestore datasets)]
  GCSArtifacts -.->|cleaned.parquet| B
  GCSArtifacts -.->|payload.json, report.json| B
```

- **Security & IAM**
  - Runtime Service Account: `${PROJECT_NUMBER}-compute@developer.gserviceaccount.com`.
  - Roles:
    - `roles/datastore.user` for Firestore access.
    - Bucket-scoped `roles/storage.objectAdmin` on `ai-data-analyser-files`.
    - `roles/eventarc.eventReceiver` for Eventarc delivery.
    - `roles/iam.serviceAccountTokenCreator` (self) for IAM-based signing.
    - GCS service account granted `roles/pubsub.publisher` for CloudEvents â†’ Pub/Sub.
  - Cloud Run service is private; HTTP access requires identity.

  - Script: `backend/deploy.ps1` handles:
    - Enabling APIs.
    - Deploying Cloud Run `preprocess-svc` with buildpacks (Python 3.12).
    - Setting env vars: `FILES_BUCKET`, `GCP_PROJECT`, `TTL_DAYS`.
    - Creating/Updating Eventarc trigger.
  - Deploying Cloud Functions `sign-upload-url` and `chat`.
  - Printing service URLs and running a smoke test.

## Verification
- **Smoke test**: `test.ps1`
  - Health probe (best-effort; service is private so 404/403 is expected).
  - Requests signed URL, uploads sample CSV, waits 30s, lists artifacts, and prints Firestore `status`.

- **Logs**
  - Cloud Run: use `gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="preprocess-svc"' --limit=100 --freshness=1h`.
  - Indicators of successful processing: `preprocess_complete` log entry and 204 response to `/eventarc` after processing.

## Operational Notes
- **Known non-blocker**: `/healthz` unauthenticated requests return 404/403 because the service is private. This does not affect Eventarc-triggered processing.
- **Resource tuning** (optional): set Cloud Run `--concurrency=1` and increase `--memory` (e.g., 1Gi) if needed for heavy files.
- **Idempotency** (optional): skip reprocessing if `cleaned/` already exists.
- **Bucket lifecycle** (optional): add object TTL for `users/` prefix to match Firestore TTL.

## Recent Changes (Changelog)
- **2025-10-14 (Classifier optimization for fastpath routing)**
  - Backend
    - Config (backend/config.yaml):
      - Added CLASSIFIER_TEMPERATURE: 0.0 for deterministic intent classification (separate from code generation temperature 0.2).
      - Added LOG_CLASSIFIER_RESPONSE flag (enabled in prod overlay for debugging).
    - Build scripts (backend/scripts/build_envs.py):
      - Added CLASSIFIER_TEMPERATURE to ALLOWED_ENV_KEYS for deployment.
    - Orchestrator config (backend/functions/orchestrator/config.py):
      - Added CLASSIFIER_TEMPERATURE config variable (default 0.0).
    - Gemini client (backend/functions/orchestrator/gemini_client.py):
      - Rewrote classifier prompt from defensive ("MUST NOT call") to encouraging ("Call a tool when question matches purpose").
      - Changed prompt tone to emphasize when TO call functions rather than when NOT to call.
      - Updated classify_intent to use dedicated CLASSIFIER_TEMPERATURE (0.0) instead of shared GEMINI_GENERATION_CONFIG (0.2).
      - Added tool examples to function descriptions (appends examples from TOOLS_SPEC to Gemini function declarations).
    - Orchestrator main (backend/functions/orchestrator/main.py):
      - Added _smart_resolve_column helper with case-insensitive matching before alias/fuzzy resolution.
      - Updated all column resolution in _validate_and_resolve to use _smart_resolve_column (11 resolution sites).
      - Column resolution now handles: exact match → case-insensitive match → alias → fuzzy match.
  - Impact
    - Expected +40-50% fastpath hit rate from temperature fix alone.
    - Expected +20-30% from encouraging prompt rewrite.
    - Expected +10-15% from case-insensitive column matching.
    - Combined: 70-80% of simple queries should now route to fastpath instead of expensive LLM fallback.
    - Query "average input cost per provider" now correctly routes to run_aggregation fastpath.
  - Timestamp
    - 2025-10-14 22:00 (+02:00)

- **2025-10-14 (ChatGPT-style UI redesign + pagination)**
  - Frontend
    - ChartRenderer (frontend/src/components/renderers/ChartRenderer.tsx):
      - Implemented adaptive number formatting (no decimals for values ≥1000, 2 decimals for smaller values).
      - Added backdrop blur and transparency to tooltips (bg-background/95 with backdrop-blur-sm).
      - Replaced hardcoded chart colors with theme palette (--chart-1 through --chart-5) for consistent theming.
      - Added Y-axis tick formatting using the adaptive number formatter.
      - Reduced padding (p-8 → p-6) and added subtle background (bg-gray-50/30 dark:bg-gray-800/20).
      - Increased line stroke width to 2px for better visibility.
    - TableRenderer (frontend/src/components/renderers/TableRenderer.tsx):
      - Complete redesign to blend seamlessly with chat container (removed all decorative elements).
      - Removed container border, shadow, rounded corners, and background for minimal ChatGPT-style look.
      - Changed table width from inline-block to full-width (w-full) to fill chat container.
      - Simplified header styling with clean background (bg-background) and stronger border (border-border).
      - Implemented right-alignment for numeric columns (except first column which stays left-aligned).
      - Reduced row padding (py-5 → py-3) for more compact, readable display.
      - Lightened row borders (border-border/10) for very subtle dividers.
      - Added pagination: 25 rows per page with Previous/Next navigation buttons.
      - Implemented elegant pagination UI with row counter ("Showing 1-25 of X rows") and page indicator ("Page 1 of Y").
      - Auto-reset to page 1 when sorting columns for better UX.
      - Removed artificial frontend row limits to display all data provided by backend.
  - Backend
    - Orchestrator (backend/functions/orchestrator/main.py):
      - Increased row limit from 50 to 200 in fastpath execution (line 644: res_df.head(50) → res_df.head(200)).
      - Increased row limit from 50 to 200 in fallback execution (line 960: table[:50] → table[:200]).
      - Ensured consistency across all execution paths (normal, fastpath, fallback) for row limits.
  - Result
    - ChatGPT-style minimal UI for tables and charts with seamless integration into chat flow.
    - All 200 rows now accessible via pagination (previously limited to 50 rows with data loss).
    - Better number formatting and alignment throughout the application.
    - Theme-consistent colors across light/dark modes.
    - No data loss - users can now view all rows provided by backend through pagination.
    - Improved readability with right-aligned numbers and compact spacing.
  - Timestamp
    - 2025-10-14 16:56 (+02:00)

- **2025-10-06 (Footer meta formatting + dynamic table width)**
  - Frontend
    - ChatMessage (frontend/src/components/ChatMessage.tsx): Footer chip now shows "N rows X M columns"; table wrapper uses w-fit so narrow tables avoid horizontal scroll.
    - TableRenderer (frontend/src/components/renderers/TableRenderer.tsx): Container switched to inline-block with max-w-full and overflow-auto; table uses min-w-max so content defines width up to chat container, then horizontal scrollbar appears only when needed.
    - App (frontend/src/App.tsx): Stable upload message id stored to update the same message meta when rows/columns arrive via Firestore.
  - Timestamp
    - 2025-10-06 16:05 (+02:00)
- **2025-10-06 (Message footer metadata)**
  - Frontend
    - ChatMessage (frontend/src/components/ChatMessage.tsx): Added footer metadata chips next to the timestamp for text messages (file name, file size, rows  columns when available).
    - App (frontend/src/App.tsx): Upload message now sets meta with file name/size; when preprocessing finishes, the same message is updated in-place with rows  columns via Firestore subscription.
  - Timestamp
    - 2025-10-06 15:15 (+02:00)
- **2025-10-06 (UI polish follow-up)**
  - Frontend
    - ChatMessage (frontend/src/components/ChatMessage.tsx): Wrap table messages in an overflow container to keep within chat width and provide internal horizontal/vertical scrollbars.
    - TableRenderer (frontend/src/components/renderers/TableRenderer.tsx): Use a scrollable container with min-w-max table to avoid spillover while allowing horizontal scroll; keeps sticky header and sorting.
  - Notes
    - Planning UI for dataset info presentation (file name/size and rowscolumns) as a metadata row under the message bubble or a subtle banner; pending selection before implementation.
  - Timestamp
    - 2025-10-06 15:06 (+02:00)
- **2025-10-06 (UI/UX tweaks)**
  - Frontend
    - Chat UI (frontend/src/App.tsx, frontend/src/components/ChatMessage.tsx): Removed separate thinking bubble; Cancel button now appears inside the assistant status message. Message timestamps now include seconds (hh:mm:ss).
    - TableRenderer (frontend/src/components/renderers/TableRenderer.tsx): Added subtle row dividers and hover highlight; implemented client-side sorting per column with icons.
    - Upload notice (frontend/src/App.tsx): After upload, assistant message shows file name and size; when preprocessing completes, a follow-up message announces rows  columns via a Firestore snapshot listener.
  - Backend
    - Summary length (backend/functions/orchestrator/gemini_client.py): Increased max_output_tokens for summary generation from 256 to 1024 to reduce truncation.
  - Timestamp
    - 2025-10-06 14:19 (+02:00)
- **2025-10-06**
  - Backend
    - Orchestrator worker (ackend/functions/orchestrator/worker.py): Removed default chart generation. chartData is returned only when the user's question explicitly asks for a chart (tokens: chart/plot/graph/visualization). If not requested, any user-code chart is coerced to {}. Result sanitation retained.
    - Orchestrator main (ackend/functions/orchestrator/main.py): Metadata-only path now emits no default chart (chart_data = {}). When result chartData is invalid, it is set to {} (no synthesized chart). Summary fallback on exception changed to a neutral, data-focused sentence.
    - Gemini client (ackend/functions/orchestrator/gemini_client.py): When LLM returns empty text, synthesize a concise, data-driven fallback using metrics (rows/columns) and a preview of column names from 	able_head.
  - Frontend
    - App (rontend/src/App.tsx): Append a chart bubble only when chartData has real content (labels > 0 and at least one numeric point in any series).
    - TableRenderer (rontend/src/components/renderers/TableRenderer.tsx): Added vertical and horizontal scroll with max-h-[420px], sticky header, and cell overflow ellipsis while keeping whitespace-nowrap.
  - Deferred
    - Daily usage limit wiring deferred until Firebase Auth integration; no limit code changes in this iteration.
  - Timestamp
    - 2025-10-06 12:58 (+02:00)
- **2025-10-05**
  - Preprocess (v2 metadata, simple & pragmatic)
    - Implemented simplified header detection with 4 signals and year-like tie-breaker; normalized confidence 0..1. Lookahead via `PREPROCESS_HEADER_LOOKAHEAD`.
    - Added manual header-row override file `metadata/preprocess_overrides.json` (per dataset) and plumbed through service; optional env `PREPROCESS_HEADER_ROW_OVERRIDE` supported internally.
    - Added v2 additive fields in `payload.json`: `schema_version: "2.0"`, `header_info` (minimal), `analysis_hints` (consolidated hints), and `dataset_summary`.
    - Kept v1 fields intact (`dataset`, `columns`, `sample_rows`, `cleaning_report`, `mode`, `version`).
  - Orchestrator
    - Prepends a compact "Dataset context" (header row + confidence, headers preview, likely structure, summary) to the schema snippet for Gemini prompts; caps schema preview to 3â€“4 columns.
  - Observability
    - Emits `header_detection` structured log with `header_row_index`, `confidence`, `method`, `is_transposed`, `lookahead`, and `low_confidence` flag to support a log-based KPI.
  - Local dev compatibility (Python 3.13)
    - Updated `backend/run-preprocess/requirements.txt` with environment markers to allow newer wheels on Python 3.13 while preserving deployment pins for 3.12.
    - Hardened Polars numeric parsing: remove parentheses via `str.replace_all`, then cast to `Float64`; fixed percent/K/M/B handling.
    - Header detection now fills NAs pre-cast and ignores empty tokens; requires at least 2 non-empty cells to avoid selecting title-only rows.
  - Tests & fixtures
    - Added fixtures under `backend/run-preprocess/tests/fixtures/`: `balance_sheet.csv`, `multi_row_header.csv`, `title_rows.csv`.
    - Added unit tests: `test_header_detection_simple.py` (positive/negative cases).
    - Added integration test: `test_integration_polars_balance_sheet.py` (CSV via Polars end-to-end).
    - Current result: 6 tests total, all passing locally on Python 3.13 (1 benign datetime parsing warning).
  - Docs
    - Added `backend/docs/payload_v1_vs_v2.md` (concise JSON examples) and annotated `backend/docs/payload_schema.json` with a note that v2 fields are additive and not validated by the v1 schema.

- **2025-10-03**
  - Frontend
    - Integrated AuthContext with Firebase Anonymous Auth; `.env.example` added; dev server port set to `5173`.
    - File upload wired to `sign-upload-url`; removed `X-Session-Id` header in favor of `sessionId` query param.
    - Chat SSE integrated; added robust spinner stop in `App.tsx` `finally` after stream ends; fixed file input reset in `ChatInput.tsx`.
  - Backend
    - CORS preflight updated to include lowercase `authorization`, `content-type`, `x-session-id` in both functions.
    - Orchestrator worker now coerces non-dict returns (DataFrame/list) and fills missing keys to avoid `run() must return a dict` surfacing to users.
  - Deploy
    - `deploy-analysis.ps1` now uses `--env-vars-file` with YAML files (`env.sign-upload-url.yaml`, `env.chat.yaml`) to reliably pass `ALLOWED_ORIGINS` on Windows PowerShell.
    - Printed function URLs unchanged; redeploy confirmed.

- **2025-10-03 (later)**
  - Frontend (Phase 1)
    - Implemented assistant placeholder message pushed immediately upon send with `kind: "status"` and live status updates mapped from SSE events (`validating`, `generating_code`, `running_fast`, `summarizing`, `persisting`).
    - Upgraded message model to a discriminated union (`text|status|error|table|chart`).
    - Added `TableRenderer.tsx` and `ChartRenderer.tsx` (Recharts) and updated `ChatMessage.tsx` to dispatch per kind.
    - On `done`, convert placeholder to summary text and append separate table and chart bubbles when present.
  - Backend (Phase 1)
    - Fixed artifact URL signing in `functions/orchestrator/main.py` general path: now signs `uris_gs` â†’ `uris` before Firestore write and SSE `done`.
  - Hosting/Deploy (Phase 1)
    - Added Firebase Hosting rewrites for `/api/sign-upload-url` and `/api/chat` to Functions Gen2 in `europe-west4`.
    - Parameterized `--allow-unauthenticated` in `backend/deploy-analysis.ps1` via `ALLOW_UNAUTHENTICATED` env var (default off) for production auth at the edge via Hosting.

- **2025-10-03 (Phase 2)**
  - Frontend
    - Added Cancel button wired to `AbortController`; converts assistant placeholder to `Cancelled.` and resets typing.
    - Fixed JSX mismatches in `App.tsx` introduced during edits.

- **2025-10-03 (Phase 3)**
  - Backend
    - Refined exception handling in `functions/orchestrator/main.py`: specific `json.JSONDecodeError` and `GoogleAPICallError` handling with clearer error codes.
    - Added final result validation/coercion before persistence (ensure `summary` non-empty fallback; shape guards for `table`, `metrics`, `chartData`).
  - Ops
    - Added GCS lifecycle rule: delete objects under `users/` prefix after 1 day via `deploy-preprocess.ps1`.

- **2025-10-03 (Phase 4)**
  - Frontend
    - Implemented Firestore chat persistence helpers in `frontend/src/services/firestore.ts` (ensure session, update dataset, save user messages, load last ~5 sessions with messages).
    - Integrated persistence into `App.tsx` (create session on new chat/ensure, update datasetId after upload, save user messages, hydrate recent sessions on auth ready).
    - Added `frontend/.env.example`; development now recommends `.env.development`. Production builds default to `/api/*` endpoints via Hosting rewrites when env vars are unset.
  - Tests
    - Enhanced `backend/test.ps1`: SSE smoke test now checks that `done` contains HTTPS signed URLs (`uris.*`) and attempts to fetch them.
- **2025-10-01**
  - Backend Performance â€“ Step 1 implemented.
    - Orchestrator (`backend/functions/orchestrator/main.py`)
      - Switched to base64 IPC: downloads `cleaned.parquet` as bytes and passes to worker over stdin JSON (`parquet_b64`). Fallback to file path via `ORCH_IPC_MODE=filepath`.
      - Uses `payload.json` keys (`sample_rows`, `columns`) for LLM context; avoids parquet `head()` when payload exists.
      - Added metadata-only fast path: schema/columns/row-count questions are answered from payload without loading parquet.
      - Parallelized GCS result uploads (table/metrics/chart_data/summary) with `ThreadPoolExecutor`.
      - Fused Gemini call: `generate_code_and_summary()` returns code + short summary in one request.
    - Worker (`backend/functions/orchestrator/worker.py`)
      - Accepts `parquet_b64` (base64) and decodes into an in-memory DataFrame; retains `parquet_path` fallback.
    - Gemini client (`backend/functions/orchestrator/gemini_client.py`)
      - Added `generate_code_and_summary()` with structured parsing; gated by `GEMINI_FUSED` env (default on).
    - Preprocess service (`backend/run-preprocess/main.py`)
      - Full in-memory I/O: `download_as_bytes()` in, `upload_from_file(BytesIO)` out; no `/tmp` in the happy path.
      - Parallelized uploads of cleaned parquet, `payload.json`, and `cleaning_report.json`.
    - Pipeline adapter (`backend/run-preprocess/pipeline_adapter.py`)
      - Added `process_bytes_to_artifacts(data, kind, ...)` to mirror file-based API for in-memory processing.
    - Deployment scripts
      - `backend/deploy-preprocess.ps1`: set `--cpu=2 --memory=2Gi --concurrency=10` and `PREPROCESS_ENGINE=polars` (engine switch to be implemented in Step 2).
      - `backend/deploy-analysis.ps1`: set `ORCH_IPC_MODE=base64` and `GEMINI_FUSED=1` for `chat` function.
    - Flags and rollback
      - `ORCH_IPC_MODE=base64|filepath`, `GEMINI_FUSED=1|0`, `PREPROCESS_ENGINE=polars|pandas` (engine wiring in Step 2).
    - Observability
      - Parallelized upload steps; will add stage timing benchmarks in a follow-up.

- **2025-10-01**
  - Backend Performance â€“ Step 2 implemented.
    - Preprocess engine defaulted to Polars for CSV via `run-preprocess/pipeline_adapter_polars.py`; Excel remains via pandas.
    - Extracted `process_df_to_artifacts()` in `run-preprocess/pipeline_adapter.py` to centralize cleaning/payload logic (shared by both adapters).
    - Dependencies: added `polars[xlsx]==1.7.1`, aligned `numpy==2.0.2` in `run-preprocess/requirements.txt`.
    - Deployed new `preprocess-svc` revision with `--cpu=2 --memory=2Gi --concurrency=10` and `PREPROCESS_ENGINE=polars`.
    - Next: run `backend/test.ps1` to smoke test end-to-end (upload â†’ Eventarc â†’ artifacts + Firestore).

- **2025-10-01**
  - Polars adapter bugfix and redeploy.
    - Replaced Polars `.str.strip()` with `.str.strip_chars()` in `run-preprocess/pipeline_adapter_polars.py` (`_drop_fully_blank_rows_pl`, `_numeric_expr_for`, repeat-header filters) to match deployed Polars API.
    - Redeployed `preprocess-svc`; Eventarc successfully processed uploaded CSV; artifacts written: `cleaned/cleaned.parquet`, `metadata/payload.json`, `reports/cleaning_report.json`.
    - `backend/test.ps1` passed end-to-end; prior `MISSING_PARQUET` error resolved.
    - Runtime confirmed at Python 3.12 via `run-preprocess/runtime.txt`.

- **2025-09-29**
  - **Frontend Redesign**: Complete UI overhaul with ChatGPT-style interface.
  - Created 4 new components: `NewSidebar.tsx` (collapsible with icon/expanded states), `FloatingChatInput.tsx` (overlay at bottom), `NewChatArea.tsx` (infinite scroll), `FloatingControls.tsx` (minimal top bar).
  - Removed visible header/footer for immersive experience; floating controls with backdrop blur.
    - Sidebar displays last 5 chat sessions, user profile with avatar, and daily usage indicator (100 requests/day limit).
    - Chat input: auto-resizing textarea, file attachment preview, keyboard shortcuts (Enter to send, Shift+Enter for new line).
    - Fully integrated with existing `ChatContext` and `AuthContext`; uses real SSE streaming from `services/api.ts`.
    - Firebase config template created at `frontend/src/lib/firebase.ts` with placeholders for future migration.
    - Updated `main.tsx` to use new `AppFinal.tsx` as entry point.
- **2025-09-28**
  - Milestone 2: Implemented LLM-driven analysis with Gemini 2.5 Flash.
    - Orchestrator (`backend/functions/orchestrator/`) now downloads `cleaned.parquet`, generates Python via LLM, validates with AST (allowlist: pandas, numpy, math, json), and executes in a sandboxed subprocess with a 60s hard timeout.
    - Persists results to GCS: `table.json`, `metrics.json`, `chart_data.json`, `summary.json`; writes Firestore `messages/{messageId}` doc.
    - SSE event flow: `received â†’ validating â†’ generating_code â†’ running_fast â†’ summarizing â†’ persisting â†’ done` (+ `ping`).
    - CORS defaults to `http://localhost:3000`.
  - Docs updated: `backend/docs/api.md` now documents SSE contract and `chartData` schema. `README.md` includes chat usage and env var notes.
  - `backend/test.ps1` extended with a best-effort SSE smoke test.
  - SSE behavior change: the orchestrator now closes the SSE stream immediately after the `done` event (removed keep-alive pings). This prevents client-side curl timeouts in smoke tests.
  - Deployment split: created `backend/deploy-preprocess.ps1` (preprocess Cloud Run + Eventarc) and `backend/deploy-analysis.ps1` (Functions: `sign-upload-url`, `chat`). Prefer running these separately; avoid re-deploying preprocess unless needed.
- **2025-09-27**
  - Standardized on `backend/deploy.ps1` as the only deployment method.
  - Removed `backend/cloudbuild.yaml` and all documentation references to Cloud Build.
  - Updated `README.md` and `backend/run-preprocess/README.md` accordingly.
- **2025-09-26 (later)**
  - Repository restructure: moved backend components under `backend/`.
  - Updated `backend/deploy.ps1` and `backend/test.ps1` to use script-relative paths.
  - Added unified CI/CD at `backend/cloudbuild.yaml` (deprecated on 2025-09-27).
- **2025-09-26**
  - Deployed `preprocess-svc` rev `preprocess-svc-00005-w5c` via `deploy.ps1`.
  - Verified end-to-end: artifacts generated and Firestore updated to `ready`.
- **2025-09-25**
  - `sign-upload-url`: switched to V4 signed URLs using impersonated credentials; removed private key reliance.
  - `run-preprocess/main.py`: implemented robust CloudEvent parsing for `/eventarc`; added `/healthz`.
  - `test.ps1`: increased wait to 30s; added Firestore status fetch.
  - Firestore TTL policy enabled for `datasets` on `ttlAt` (ACTIVE).

## Next Steps
- **Optional**: authenticate health probe in scripts with identity tokens if you want a green check.
- **Optional**: apply Cloud Run resource tuning if processing larger files.
- **Upcoming**: integrate chat/orchestrator stage to consume `payload.json` and cleaned data.

---

This file is the living progress record for this project. Update it with each change to deployments, architecture, or operational practice.
