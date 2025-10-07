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

# Configuration
PROJECT_ID = os.getenv("GCP_PROJECT", "ai-data-analyser")
FILES_BUCKET = os.getenv("FILES_BUCKET", "ai-data-analyser-files")
PING_INTERVAL_SECONDS = int(os.getenv("SSE_PING_INTERVAL_SECONDS", "22"))
HARD_TIMEOUT_SECONDS = int(os.getenv("CHAT_HARD_TIMEOUT_SECONDS", "60"))
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
    code, is_valid, validation_errors = "", False, ["Code generation failed."]
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            raw_code, llm_response_text = gemini_client.generate_code_and_summary(question, schema_snippet, sample_rows)
            
            if not raw_code:
                # If code extraction fails, use the raw response for the repair prompt
                validation_errors = [f"LLM did not return a valid code block. Response: {llm_response_text[:200]}"]
                question = f"The previous attempt failed. Please fix it. The error was: {validation_errors[0]}. Original question: {question}"
                continue # Retry

            # --- FIX: Unpack all three return values from the validator ---
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
    
    # --- Execute the validated code ---
    yield _sse_format({"type": "running_fast"})
    try:
        parquet_gcs_path = f"users/{uid}/sessions/{session_id}/datasets/{dataset_id}/cleaned/cleaned.parquet"
        parquet_blob = bucket.blob(parquet_gcs_path)
        parquet_bytes = parquet_blob.download_as_bytes()
        parquet_b64 = base64.b64encode(parquet_bytes).decode("ascii")

        worker_path = os.path.join(os.path.dirname(__file__), "worker.py")
        proc = subprocess.run(
            [sys.executable, worker_path],
            input=json.dumps({"code": code, "parquet_b64": parquet_b64, "ctx": {}}).encode("utf-8"),
            capture_output=True,
            timeout=HARD_TIMEOUT_SECONDS,
        )

        if proc.returncode != 0:
            raise RuntimeError(f"Worker process failed: {proc.stderr.decode('utf-8', errors='ignore')}")
        
        result = json.loads(proc.stdout)
        if result.get("error"):
             raise RuntimeError(f"Execution error: {result['error']}")

    except Exception as e:
        yield _sse_format({"type": "error", "data": {"code": "EXEC_FAILED", "message": str(e)}})
        return

    # Process and persist results
    message_id = str(uuid.uuid4())
    table = result.get("tables", [])[0] if result.get("tables") else [] # Assuming one table for now
    chart_data = result.get("charts", [])[0] if result.get("charts") else {}
    
    yield _sse_format({"type": "summarizing"})
    summary = result.get("summary") or gemini_client.generate_summary(question, table[:5], {})
    
    yield _sse_format({"type": "persisting"})
    # ... (Persist logic for table, chart_data, summary to GCS) ...
    
    # Final 'done' event
    yield _sse_format({
        "type": "done",
        "data": { "messageId": message_id, "summary": summary, "tableSample": table[:50], "chartData": chart_data }
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
