import json
import os
import time
import uuid
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from typing import Generator, Iterable

import functions_framework
from flask import Request, Response
from google.cloud import firestore
from google.cloud import storage
import pandas as pd
import base64
from concurrent.futures import ThreadPoolExecutor
import pyarrow as pa  # type: ignore
import pyarrow.parquet as pq  # type: ignore

import firebase_admin
from firebase_admin import auth as fb_auth
import google.auth
from google.auth import impersonated_credentials
import google.auth.transport.requests

import gemini_client
import sandbox_runner
from google.api_core import exceptions as gax_exceptions  # type: ignore

# Optional: read payload from GCS later if needed
# from google.cloud import storage

PROJECT_ID = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "ai-data-analyser"))
FILES_BUCKET = os.getenv("FILES_BUCKET", "ai-data-analyser-files")
PING_INTERVAL_SECONDS = int(os.getenv("SSE_PING_INTERVAL_SECONDS", "22"))
HARD_TIMEOUT_SECONDS = int(os.getenv("CHAT_HARD_TIMEOUT_SECONDS", "60"))
ORCH_IPC_MODE = os.getenv("ORCH_IPC_MODE", "base64").lower()
RUNTIME_SERVICE_ACCOUNT = os.getenv("RUNTIME_SERVICE_ACCOUNT")

# Allowed origins (comma-separated). Default supports local dev and Firebase Hosting.
ALLOWED_ORIGINS = {
    o.strip()
    for o in (os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,https://ai-data-analyser.web.app,https://ai-data-analyser.firebaseapp.com",
    ) or "").split(",")
    if o.strip()
}


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    return origin in ALLOWED_ORIGINS


# Cache for signing credentials used for V4 signing
_CACHED_SIGNING_CREDS = None
_CACHED_EXPIRES_AT = 0.0


def _impersonated_signing_credentials(sa_email: str | None):
    """Create impersonated credentials for signing using IAM Credentials API.

    Requires that the runtime service account has roles/iam.serviceAccountTokenCreator
    on the target principal (can be itself). Also requires the
    iamcredentials.googleapis.com API to be enabled.
    """
    global _CACHED_SIGNING_CREDS, _CACHED_EXPIRES_AT

    now = time.time()
    if _CACHED_SIGNING_CREDS is not None and now < _CACHED_EXPIRES_AT:
        return _CACHED_SIGNING_CREDS

    if not sa_email:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _CACHED_SIGNING_CREDS = creds
        _CACHED_EXPIRES_AT = now + 3300  # ~55m
        return _CACHED_SIGNING_CREDS

    source_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if getattr(source_creds, "token", None) is None:
        source_creds.refresh(google.auth.transport.requests.Request())

    _CACHED_SIGNING_CREDS = impersonated_credentials.Credentials(
        source_credentials=source_creds,
        target_principal=sa_email,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=3600,
    )
    _CACHED_EXPIRES_AT = now + 3300
    return _CACHED_SIGNING_CREDS


def _sign_gs_uri(gs_uri: str, minutes: int = 15) -> str:
    """Return a signed HTTPS URL for the given gs:// URI. If not gs://, return as-is."""
    if not gs_uri or not gs_uri.startswith("gs://"):
        return gs_uri
    no_scheme = gs_uri[5:]
    parts = no_scheme.split("/", 1)
    if len(parts) != 2:
        return gs_uri
    bucket_name, blob_path = parts[0], parts[1]
    storage_client = storage.Client(project=PROJECT_ID)
    blob = storage_client.bucket(bucket_name).blob(blob_path)
    signing_creds = _impersonated_signing_credentials(RUNTIME_SERVICE_ACCOUNT)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=minutes),
        method="GET",
        credentials=signing_creds,
    )


def _sign_uris(uris: dict | None) -> dict:
    d = uris or {}
    return {k: _sign_gs_uri(v) for k, v in d.items()}


# Initialize Firebase Admin SDK
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()


def _sse_format(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _heartbeat() -> str:
    return _sse_format({"type": "ping", "ts": datetime.now(timezone.utc).isoformat()})


def _events(session_id: str, dataset_id: str, uid: str, question: str) -> Iterable[str]:
    # received
    yield _sse_format({"type": "received", "data": {"sessionId": session_id, "datasetId": dataset_id}})

    # validating (placeholder)
    yield _sse_format({"type": "validating"})

    # Prepare GCS paths
    dataset_prefix = f"users/{uid}/sessions/{session_id}/datasets/{dataset_id}"
    parquet_gcs = f"{dataset_prefix}/cleaned/cleaned.parquet"
    payload_gcs = f"{dataset_prefix}/metadata/payload.json"
    message_id = str(uuid.uuid4())

    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(FILES_BUCKET)

    # Attempt to fetch payload first (for sample/schema and potential metadata-only fast path)
    payload_obj: dict = {}
    try:
        payload_blob = bucket.blob(payload_gcs)
        if payload_blob.exists(storage_client):
            payload_text = payload_blob.download_as_text()
            payload_obj = json.loads(payload_text)
    except Exception:
        payload_obj = {}

    # Load schema/sample from payload.json if present (preferred)
    schema_snippet = ""
    sample_rows: list[dict] = []
    ctx: dict = {"limits": {"sampleRowsForDisplay": 50, "maxCharts": 0}}
    try:
        if isinstance(payload_obj, dict):
            # Our payload emits: columns (dict), dataset meta, and sample_rows (list)
            cols = payload_obj.get("columns")
            header_info = payload_obj.get("header_info") or {}
            hints = payload_obj.get("analysis_hints") or {}
            dataset_summary = payload_obj.get("dataset_summary") or ""

            # Build compact context lines if v2 present
            context_lines: list[str] = []
            if header_info or hints or dataset_summary:
                hrow = header_info.get("header_row_index")
                conf = header_info.get("confidence")
                method = header_info.get("method")
                final_headers = header_info.get("final_headers") or []
                hdr_preview = final_headers[:4] if isinstance(final_headers, list) else []
                first_col_type = hints.get("first_column_type")
                likely_pivoted = hints.get("likely_pivoted")
                context_lines.append("Dataset context:")
                parts = []
                if hrow is not None and conf is not None:
                    parts.append(f"- Detected header row: {hrow} (confidence {float(conf):.2f}{', ' + method if method else ''})")
                if hdr_preview:
                    parts.append(f"- Headers: {hdr_preview}")
                if first_col_type is not None or likely_pivoted is not None:
                    parts.append(f"- Likely structure: first column = {first_col_type}, likely_pivoted={bool(likely_pivoted)}")
                if dataset_summary:
                    parts.append(f"- Summary: {dataset_summary}")
                context_lines.extend(parts)

            # Columns preview (limit 3–4 entries for readability)
            cols_preview_json = ""
            if isinstance(cols, dict):
                # take first 4 items
                items = list(cols.items())[:4]
                cols_preview_json = json.dumps({k: v for k, v in items})
            elif isinstance(cols, list):
                cols_preview_json = json.dumps(cols[:4])

            # Assemble schema_snippet
            if context_lines or cols_preview_json:
                schema_snippet = ("\n".join(context_lines) + ("\n" if context_lines else "") + (cols_preview_json or ""))[:1000]

            sr = payload_obj.get("sample_rows")
            if isinstance(sr, list):
                sample_rows = sr[:10]

            # Build ctx from payload
            dataset_meta = payload_obj.get("dataset") or {}
            final_headers = header_info.get("final_headers") or []
            dtypes = dataset_meta.get("dtypes") or {}
            ctx["dataset"] = {
                "rows": int(dataset_meta.get("rows") or 0),
                "columns": int(dataset_meta.get("columns") or 0),
                "column_names": final_headers if isinstance(final_headers, list) and final_headers else list(dtypes.keys()),
                "dtypes": dtypes if isinstance(dtypes, dict) else {},
            }
            # Map numeric/temporal indices to names if possible
            def _map_indices(indices: list[int]) -> list[str]:
                try:
                    if isinstance(indices, list) and final_headers:
                        return [str(final_headers[i]) for i in indices if 0 <= i < len(final_headers)]
                except Exception:
                    return []
                return []
            numeric_names = _map_indices(hints.get("numeric_columns") or [])
            temporal_names = _map_indices(hints.get("temporal_columns") or [])
            ctx["hints"] = {"numeric": numeric_names, "temporal": temporal_names}
    except Exception:
        sample_rows = []

    # Metadata-only fast path: answer simple schema/rows questions without loading parquet
    def _is_metadata_only(q: str) -> bool:
        ql = (q or "").lower()
        tokens = [
            "column", "columns", "schema", "datatype", "data type", "types",
            "row count", "rows", "how many rows", "number of rows", "num rows",
        ]
        return any(t in ql for t in tokens)

    if _is_metadata_only(question) and payload_obj:
        # Build lightweight artifacts from payload alone
        dataset_meta = (payload_obj.get("dataset") or {}) if isinstance(payload_obj, dict) else {}
        total_rows = int(dataset_meta.get("rows") or 0)
        total_cols = int(dataset_meta.get("columns") or 0)
        table = sample_rows or []
        metrics = {"rows": total_rows, "columns": total_cols}
        # Do not render a default chart in metadata-only answers
        chart_data = {}

        # Persist and done (no parquet or worker)
        yield _sse_format({"type": "persisting"})
        results_prefix = f"users/{uid}/sessions/{session_id}/results/{message_id}"
        uris_gs = {
            "table": f"gs://{FILES_BUCKET}/{results_prefix}/table.json",
            "metrics": f"gs://{FILES_BUCKET}/{results_prefix}/metrics.json",
            "chartData": f"gs://{FILES_BUCKET}/{results_prefix}/chart_data.json",
            "summary": f"gs://{FILES_BUCKET}/{results_prefix}/summary.json",
        }
        try:
            with ThreadPoolExecutor(max_workers=4) as ex:
                futs = []
                futs.append(ex.submit(bucket.blob(f"{results_prefix}/table.json").upload_from_string,
                                     json.dumps(table, ensure_ascii=False), content_type="application/json"))
                futs.append(ex.submit(bucket.blob(f"{results_prefix}/metrics.json").upload_from_string,
                                     json.dumps(metrics, ensure_ascii=False), content_type="application/json"))
                futs.append(ex.submit(bucket.blob(f"{results_prefix}/chart_data.json").upload_from_string,
                                     json.dumps(chart_data, ensure_ascii=False), content_type="application/json"))
                futs.append(ex.submit(bucket.blob(f"{results_prefix}/summary.json").upload_from_string,
                                     json.dumps({"summary": "Dataset metadata provided."}, ensure_ascii=False), content_type="application/json"))
                for f in futs:
                    f.result()
        except Exception as e:  # noqa: BLE001
            yield _sse_format({"type": "error", "data": {"code": "PERSIST_FAILED", "message": str(e)[:400]}})
            return

        # Sign artifact URIs for browser access
        uris = _sign_uris(uris_gs)

        fs = firestore.Client(project=PROJECT_ID)
        fs.collection("users").document(uid).collection("sessions").document(session_id).collection("messages").document(message_id).set({
            "role": "assistant",
            "question": question,
            "content": "Dataset metadata provided.",
            "createdAt": datetime.now(timezone.utc),
            "status": "done",
            "uris": uris,
        })

        yield _sse_format({
            "type": "done",
            "data": {
                "messageId": message_id,
                "chartData": chart_data,
                "tableSample": table[: min(len(table), 50)],
                "uris": uris,
                "urisGs": uris_gs,
                "summary": "Dataset metadata provided.",
            },
        })
        return

    # generating_code via Gemini (fused pre-run: code + summary)
    yield _sse_format({"type": "generating_code"})
    try:
        code, pre_summary = gemini_client.generate_code_and_summary(question, schema_snippet, sample_rows)
    except Exception as e:  # noqa: BLE001
        yield _sse_format({"type": "error", "data": {"code": "CODEGEN_FAILED", "message": str(e)[:400]}})
        return

    # Validate code (AST)
    ok, errs = sandbox_runner.validate_code(code)
    if not ok:
        yield _sse_format({"type": "error", "data": {"code": "CODE_VALIDATION_FAILED", "message": "; ".join(errs)[:400]}})
        return

    # Prepare data transfer for child process
    parquet_b64: str | None = None
    arrow_ipc_b64: str | None = None
    parquet_path: str | None = None
    # Download parquet as needed for analysis
    try:
        blob = bucket.blob(parquet_gcs)
        if not blob.exists(storage_client):
            yield _sse_format({"type": "error", "data": {"code": "MISSING_PARQUET", "message": parquet_gcs}})
            return
        if ORCH_IPC_MODE == "base64":
            parquet_bytes = blob.download_as_bytes()
            parquet_b64 = base64.b64encode(parquet_bytes).decode("ascii")
        elif ORCH_IPC_MODE == "arrow":
            # Download parquet bytes → read as Arrow Table → serialize IPC stream
            parquet_bytes = blob.download_as_bytes()
            table_arrow = pq.read_table(pa.BufferReader(parquet_bytes))
            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, table_arrow.schema) as writer:
                writer.write_table(table_arrow)
            arrow_ipc_b64 = base64.b64encode(sink.getvalue().to_pybytes()).decode("ascii")
        else:
            parquet_path = f"/tmp/{dataset_id}_cleaned.parquet"
            blob.download_to_filename(parquet_path)
    except Exception as e:  # noqa: BLE001
        yield _sse_format({"type": "error", "data": {"code": "DOWNLOAD_FAILED", "message": str(e)[:300]}})
        return

    # Execute in child process
    yield _sse_format({"type": "running_fast"})
    worker_path = os.path.join(os.path.dirname(__file__), "worker.py")
    try:
        # Attach question into ctx for worker-side heuristics
        try:
            ctx["question"] = question
        except Exception:
            pass

        proc = subprocess.run(
            [os.environ.get("PYTHON_EXECUTABLE", sys.executable), worker_path],
            input=json.dumps({
                "code": code,
                "parquet_b64": parquet_b64,
                "arrow_ipc_b64": arrow_ipc_b64,
                "parquet_path": parquet_path,
                "ctx": ctx,
            }).encode("utf-8"),
            capture_output=True,
            timeout=HARD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        yield _sse_format({"type": "error", "data": {"code": "TIMEOUT_HARD", "message": "Operation exceeded 60s"}})
        return

    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="ignore")[:500]
        yield _sse_format({"type": "error", "data": {"code": "EXEC_FAILED", "message": err}})
        return

    try:
        result = json.loads(proc.stdout.decode("utf-8"))
    except json.JSONDecodeError as e:  # type: ignore[attr-defined]
        yield _sse_format({"type": "error", "data": {"code": "BAD_RESULT_JSON", "message": str(e)[:300]}})
        return
    except Exception as e:  # noqa: BLE001
        yield _sse_format({"type": "error", "data": {"code": "BAD_RESULT", "message": str(e)[:300]}})
        return

    table = result.get("table") or []
    metrics = result.get("metrics") or {}
    chart_data = result.get("chartData") or {}
    # Final validation/coercion before persist
    if not isinstance(table, list):
        table = []
    if not isinstance(metrics, dict):
        metrics = {}
    if not isinstance(chart_data, dict):
        # Do not synthesize a default chart; only show charts when explicitly requested
        chart_data = {}
    table_sample = table[: min(len(table), 50)]

    # summarizing (generate summary from actual results)
    yield _sse_format({"type": "summarizing"})
    try:
        summary = gemini_client.generate_summary(question, table_sample, metrics, code=code)
    except Exception as e:
        print(f"WARNING: Summary generation failed: {e}", file=sys.stderr)
        # Fallback to the pre-run summary if post-run generation fails, else neutral message
        summary = pre_summary or "No textual summary available. See the table for details."

    # persist
    yield _sse_format({"type": "persisting"})
    results_prefix = f"users/{uid}/sessions/{session_id}/results/{message_id}"
    uris_gs = {
        "table": f"gs://{FILES_BUCKET}/{results_prefix}/table.json",
        "metrics": f"gs://{FILES_BUCKET}/{results_prefix}/metrics.json",
        "chartData": f"gs://{FILES_BUCKET}/{results_prefix}/chart_data.json",
        "summary": f"gs://{FILES_BUCKET}/{results_prefix}/summary.json",
    }
    try:
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = []
            futs.append(ex.submit(bucket.blob(f"{results_prefix}/table.json").upload_from_string,
                                 json.dumps(table, ensure_ascii=False), content_type="application/json"))
            futs.append(ex.submit(bucket.blob(f"{results_prefix}/metrics.json").upload_from_string,
                                 json.dumps(metrics, ensure_ascii=False), content_type="application/json"))
            futs.append(ex.submit(bucket.blob(f"{results_prefix}/chart_data.json").upload_from_string,
                                 json.dumps(chart_data, ensure_ascii=False), content_type="application/json"))
            futs.append(ex.submit(bucket.blob(f"{results_prefix}/summary.json").upload_from_string,
                                 json.dumps({"summary": summary}, ensure_ascii=False), content_type="application/json"))
            for f in futs:
                f.result()
    except gax_exceptions.GoogleAPICallError as e:  # type: ignore[attr-defined]
        yield _sse_format({"type": "error", "data": {"code": "PERSIST_API_ERROR", "message": str(e)[:400]}})
        return
    except Exception as e:  # noqa: BLE001
        yield _sse_format({"type": "error", "data": {"code": "PERSIST_FAILED", "message": str(e)[:400]}})
        return

    # Firestore message doc
    try:
        fs = firestore.Client(project=PROJECT_ID)
        doc_path = f"users/{uid}/sessions/{session_id}/messages/{message_id}"
        print(f"DEBUG: Preparing to write to Firestore path: {doc_path}")

        # Check for empty or None values in the path
        if not all([uid, session_id, message_id]):
            print(f"CRITICAL ERROR: One or more IDs are empty. UID='{uid}', SessionID='{session_id}', MessageID='{message_id}'. Aborting Firestore write.", file=sys.stderr)
            yield _sse_format({"type": "error", "data": {"code": "FIRESTORE_PATH_INVALID", "message": "UID, session, or message ID was empty."}})
            return

        msg_data = {
            "uid": uid,
            "sessionId": session_id,
            "datasetId": dataset_id,
            "question": question,
            "summary": summary,
            "tableSample": table_sample,
            "chartData": chart_data,
            "uris": uris_gs,  # Storing the gs:// URIs in Firestore
            "createdAt": firestore.SERVER_TIMESTAMP,
            "role": "assistant",
            "status": "done",
        }
        
        print(f"DEBUG: Data for Firestore: {json.dumps(msg_data, indent=2, default=str)}")

        msg_ref = fs.document(doc_path)
        msg_ref.set(msg_data)
        
        print("DEBUG: Firestore write successful.")

    except Exception as e:
        print(f"CRITICAL ERROR during Firestore write: {e}", file=sys.stderr)
        yield _sse_format({"type": "error", "data": {"code": "FIRESTORE_WRITE_FAILED", "message": str(e)}})
        return # Stop execution if Firestore fails
    
    # Sign artifact URIs for browser access (general path)
    print("DEBUG: Signing URIs for SSE response...")
    uris = _sign_uris(uris_gs)

    # done
    yield _sse_format({
        "type": "done",
        "data": {
            "messageId": message_id,
            "chartData": chart_data,
            "tableSample": table_sample,
            "uris": uris,
            "urisGs": uris_gs,
            "summary": summary,
        },
    })
    # Close stream after final event (Option B)
    return


@functions_framework.http
def chat(request: Request) -> Response:
    origin = request.headers.get("Origin") or ""
    if request.method == "OPTIONS":
        if not _origin_allowed(origin):
            return ("Origin not allowed", 403, {"Content-Type": "text/plain"})
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            # Include lowercase variants to match Access-Control-Request-Headers from browsers
            "Access-Control-Allow-Headers": "Content-Type, content-type, Authorization, authorization, X-Session-Id, x-session-id",
            "Access-Control-Max-Age": "3600",
            "Cache-Control": "no-store",
        }
        return ("", 204, headers)

    try:
        if not _origin_allowed(origin):
            return (json.dumps({"error": "origin not allowed"}), 403, {"Content-Type": "application/json"})

        # Verify Firebase ID token
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.split(" ", 1)[1] if auth_header.lower().startswith("bearer ") else None
        if not token:
            return (json.dumps({"error": "missing Authorization Bearer token"}), 401, {"Content-Type": "application/json"})
        try:
            decoded = fb_auth.verify_id_token(token)
            uid = decoded.get("uid")
        except Exception as e:  # noqa: BLE001
            return (json.dumps({"error": "invalid token", "detail": str(e)[:200]}), 401, {"Content-Type": "application/json"})

        payload = request.get_json(silent=True) or {}
        session_id = payload.get("sessionId") or request.headers.get("X-Session-Id")
        dataset_id = payload.get("datasetId")
        question = payload.get("question") or ""
        if not all([session_id, dataset_id, uid]):
            return (json.dumps({"error": "missing sessionId or datasetId"}), 400, {"Content-Type": "application/json"})

        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": origin,
        }
        return Response(_events(session_id, dataset_id, uid, question), headers=headers, status=200)
    except Exception as e:  # noqa: BLE001
        return (json.dumps({"error": "internal error", "detail": str(e)[:500]}), 500, {"Content-Type": "application/json"})

