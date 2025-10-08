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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
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

# Configuration
PROJECT_ID = os.getenv("GCP_PROJECT", "ai-data-analyser")
FILES_BUCKET = os.getenv("FILES_BUCKET", "ai-data-analyser-files")
PING_INTERVAL_SECONDS = int(os.getenv("SSE_PING_INTERVAL_SECONDS", "22"))
HARD_TIMEOUT_SECONDS = int(os.getenv("CHAT_HARD_TIMEOUT_SECONDS", "60"))
REPAIR_TIMEOUT_SECONDS = int(os.getenv("CHAT_REPAIR_TIMEOUT_SECONDS", "30"))
ORCH_IPC_MODE = os.getenv("ORCH_IPC_MODE", "base64").lower()
RUNTIME_SERVICE_ACCOUNT = os.getenv("RUNTIME_SERVICE_ACCOUNT")

ALLOWED_ORIGINS = {
    o.strip()
    for o in (os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,https://ai-data-analyser.web.app,https://ai-data-analyser.firebaseapp.com",
    ) or "").split(",")
    if o.strip()
}

# Firebase Admin SDK Initialization
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()


def _origin_allowed(origin: str | None) -> bool:
    return origin in ALLOWED_ORIGINS if origin else False


_CACHED_SIGNING_CREDS = None
_CACHED_EXPIRES_AT = 0.0

def _impersonated_signing_credentials(sa_email: str | None):
    """Creates and caches impersonated credentials for signing URLs."""
    global _CACHED_SIGNING_CREDS, _CACHED_EXPIRES_AT
    now = time.time()
    if _CACHED_SIGNING_CREDS and now < _CACHED_EXPIRES_AT:
        return _CACHED_SIGNING_CREDS

    source_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not sa_email:
        creds = source_creds
    else:
        creds = impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=sa_email,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            lifetime=3600,
        )
    _CACHED_SIGNING_CREDS = creds
    _CACHED_EXPIRES_AT = now + 3300  # ~55m
    return _CACHED_SIGNING_CREDS


def _sign_gs_uri(gs_uri: str, minutes: int = 15) -> str:
    """Returns a signed HTTPS URL for a gs:// URI."""
    if not gs_uri or not gs_uri.startswith("gs://"):
        return gs_uri
    try:
        bucket_name, blob_path = gs_uri[5:].split("/", 1)
        storage_client = storage.Client(project=PROJECT_ID)
        blob = storage_client.bucket(bucket_name).blob(blob_path)
        signing_creds = _impersonated_signing_credentials(RUNTIME_SERVICE_ACCOUNT)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=minutes),
            method="GET",
            credentials=signing_creds,
        )
    except Exception:
        return gs_uri


def _sse_format(obj: dict) -> str:
    """Formats a dictionary as a Server-Sent Event string."""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _events(session_id: str, dataset_id: str, uid: str, question: str) -> Iterable[str]:
    """Generator function for the main SSE event stream."""
    yield _sse_format({"type": "received", "data": {"sessionId": session_id, "datasetId": dataset_id}})

    # Setup GCS and Firestore clients
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(FILES_BUCKET)
    fs = firestore.Client(project=PROJECT_ID)

    # Fetch payload.json for schema and sample data
    payload_obj = {}
    try:
        payload_gcs_path = f"users/{uid}/sessions/{session_id}/datasets/{dataset_id}/metadata/payload.json"
        payload_blob = bucket.blob(payload_gcs_path)
        payload_obj = json.loads(payload_blob.download_as_text())
    except Exception as e:
        yield _sse_format({"type": "error", "data": {"code": "PAYLOAD_READ_FAILED", "message": f"Could not read metadata: {e}"}})
        return

    schema_snippet = json.dumps(payload_obj.get("columns", {}))[:1000]
    sample_rows = payload_obj.get("sample_rows", [])[:10]

    # --- Main Generation and Validation Loop ---
    yield _sse_format({"type": "generating_code"})
    code, is_valid, validation_errors, warnings = "", False, ["Code generation failed."], []
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            raw_code, llm_response_text = gemini_client.generate_code_and_summary(question, schema_snippet, sample_rows)
            
            if not raw_code:
                # If code extraction fails, use the raw response for the repair prompt
                validation_errors = [f"LLM did not return a valid code block. Response: {llm_response_text[:200]}"]
                question = f"The previous attempt failed. Please fix it. The error was: {validation_errors[0]}. Original question: {question}"
                continue # Retry

            # ✅ FIX 1: Unpack all three return values from the validator
            is_valid, validation_errors, warnings = sandbox_runner.validate_code(raw_code)
            
            if is_valid:
                code = raw_code
                break # Success
            else:
                # If validation fails, use the errors for the repair prompt
                question = f"The previous code failed validation. Please fix it. Errors: {'; '.join(validation_errors)}. Original question: {question}"

        except Exception as e:
            validation_errors = [f"An unexpected error occurred during code generation: {e}"]

    if not is_valid or not code:
        yield _sse_format({"type": "error", "data": {"code": "CODE_VALIDATION_FAILED", "message": "; ".join(validation_errors)}})
        return
    
    # --- Emit the validated code so the UI can display it (even if execution fails) ---
    try:
        yield _sse_format({
            "type": "code",
            "data": {
                "language": "python",
                "text": code,
                "warnings": (warnings or [])
            }
        })
    except Exception:
        # Non-fatal: continue workflow even if emitting this event fails
        pass

    # --- Execute the validated code (with one-time repair on failure) ---
    yield _sse_format({"type": "running_fast"})
    parquet_gcs_path = f"users/{uid}/sessions/{session_id}/datasets/{dataset_id}/cleaned/cleaned.parquet"
    try:
        parquet_blob = bucket.blob(parquet_gcs_path)
        parquet_bytes = parquet_blob.download_as_bytes()
        parquet_b64 = base64.b64encode(parquet_bytes).decode("ascii")
    except Exception as e:
        yield _sse_format({"type": "error", "data": {"code": "DATA_READ_FAILED", "message": str(e)}})
        return

    def _run_once(code_to_run: str) -> dict:
        worker_path = os.path.join(os.path.dirname(__file__), "worker.py")
        proc = subprocess.run(
            [sys.executable, worker_path],
            input=json.dumps({
                "code": code_to_run,
                "parquet_b64": parquet_b64,
                "ctx": {"question": question, "row_limit": 200},
            }).encode("utf-8"),
            capture_output=True,
            timeout=HARD_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Worker process failed: {proc.stderr.decode('utf-8', errors='ignore')}")
        return json.loads(proc.stdout)

    tried_repair = False
    try:
        result = _run_once(code)
        if result.get("error"):
            raise RuntimeError(f"Execution error: {result['error']}")
    except subprocess.TimeoutExpired:
        yield _sse_format({"type": "error", "data": {"code": "TIMEOUT_HARD", "message": f"Execution timed out after {HARD_TIMEOUT_SECONDS}s"}})
        return
    except Exception as e_first:
        # Attempt a single repair using the runtime error
        try:
            tried_repair = True
            yield _sse_format({"type": "repairing"})
            # Bound the repair step to avoid indefinite hangs
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(gemini_client.repair_code, question, schema_snippet, sample_rows, code, str(e_first))
                try:
                    repaired = future.result(timeout=REPAIR_TIMEOUT_SECONDS)
                except FuturesTimeout:
                    yield _sse_format({"type": "error", "data": {"code": "REPAIR_TIMEOUT", "message": f"Repair step timed out after {REPAIR_TIMEOUT_SECONDS}s"}})
                    return
            ok2, errs2, warns2 = sandbox_runner.validate_code(repaired)
            if not ok2:
                yield _sse_format({"type": "error", "data": {"code": "CODE_VALIDATION_FAILED", "message": "; ".join(errs2)}})
                return
            code = repaired
            warnings = warns2
            # Emit updated code for the UI
            try:
                yield _sse_format({
                    "type": "code",
                    "data": {"language": "python", "text": code, "warnings": (warnings or [])}
                })
            except Exception:
                pass
            # Re-run once
            yield _sse_format({"type": "running_fast"})
            result = _run_once(code)
            if result.get("error"):
                raise RuntimeError(f"Execution error: {result['error']}")
        except subprocess.TimeoutExpired:
            yield _sse_format({"type": "error", "data": {"code": "TIMEOUT_HARD", "message": f"Execution timed out after {HARD_TIMEOUT_SECONDS}s"}})
            return
        except Exception as e_second:
            # Final failure after repair attempt
            yield _sse_format({"type": "error", "data": {"code": "EXEC_FAILED", "message": str(e_second)}})
            return

    # ✅ FIX 2: Correct key names (singular, not plural)
    message_id = str(uuid.uuid4())
    table = result.get("table", [])  # "table" not "tables"
    chart_data = result.get("chartData", {})  # "chartData" not "charts"
    metrics = result.get("metrics", {})
    
    yield _sse_format({"type": "summarizing"})
    summary = result.get("summary") or gemini_client.generate_summary(question, table[:5], metrics)
    
    # ✅ FIX 3: Add actual persistence logic
    yield _sse_format({"type": "persisting"})
    
    results_prefix = f"users/{uid}/sessions/{session_id}/results/{message_id}"
    table_path = f"{results_prefix}/table.json"
    metrics_path = f"{results_prefix}/metrics.json"
    chart_path = f"{results_prefix}/chart_data.json"
    summary_path = f"{results_prefix}/summary.json"
    
    try:
        table_blob = bucket.blob(table_path)
        metrics_blob = bucket.blob(metrics_path)
        chart_blob = bucket.blob(chart_path)
        summary_blob = bucket.blob(summary_path)
        
        table_data = json.dumps({"rows": table}, ensure_ascii=False).encode("utf-8")
        metrics_data = json.dumps(metrics, ensure_ascii=False).encode("utf-8")
        chart_data_json = json.dumps(chart_data, ensure_ascii=False).encode("utf-8")
        summary_data = json.dumps({"text": summary}, ensure_ascii=False).encode("utf-8")
        
        # Upload in parallel
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(table_blob.upload_from_string, table_data, content_type="application/json"),
                executor.submit(metrics_blob.upload_from_string, metrics_data, content_type="application/json"),
                executor.submit(chart_blob.upload_from_string, chart_data_json, content_type="application/json"),
                executor.submit(summary_blob.upload_from_string, summary_data, content_type="application/json"),
            ]
            for f in futures:
                f.result()
        
        # Generate signed URLs for frontend
        table_url = _sign_gs_uri(f"gs://{FILES_BUCKET}/{table_path}")
        metrics_url = _sign_gs_uri(f"gs://{FILES_BUCKET}/{metrics_path}")
        chart_url = _sign_gs_uri(f"gs://{FILES_BUCKET}/{chart_path}")
        summary_url = _sign_gs_uri(f"gs://{FILES_BUCKET}/{summary_path}")
        
    except Exception as e:
        yield _sse_format({"type": "error", "data": {"code": "PERSIST_FAILED", "message": str(e)}})
        return
    
    # Final 'done' event with URLs
    yield _sse_format({
        "type": "done",
        "data": {
            "messageId": message_id,
            "summary": summary,
            "tableSample": table[:50],  # Now works correctly
            "chartData": chart_data,
            "metrics": metrics,
            "uris": {
                "table": table_url,
                "metrics": metrics_url,
                "chartData": chart_url,
                "summary": summary_url
            }
        }
    })


@functions_framework.http
def chat(request: Request) -> Response:
    """HTTP entry point for the chat Cloud Function."""
    origin = request.headers.get("Origin") or ""
    if request.method == "OPTIONS":
        if not _origin_allowed(origin): return ("Origin not allowed", 403)
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Session-Id",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    try:
        if not _origin_allowed(origin):
            return Response(json.dumps({"error": "origin not allowed"}), 403, mimetype="application/json")

        auth_header = request.headers.get("Authorization", "")
        token = auth_header.split(" ", 1)[1] if auth_header.lower().startswith("bearer ") else None
        if not token:
            return Response(json.dumps({"error": "missing token"}), 401, mimetype="application/json")
        
        decoded = fb_auth.verify_id_token(token)
        uid = decoded["uid"]
        
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("sessionId")
        dataset_id = payload.get("datasetId")
        question = payload.get("question", "")
        
        if not all([session_id, dataset_id, uid]):
            return Response(json.dumps({"error": "missing sessionId or datasetId"}), 400, mimetype="application/json")

        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": origin,
        }
        return Response(_events(session_id, dataset_id, uid, question), headers=headers)

    except Exception as e:
        return Response(json.dumps({"error": "internal error", "detail": str(e)}), 500, mimetype="application/json")