import json
import os
import time
import uuid
import subprocess
import sys
from datetime import datetime, timezone
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

import gemini_client
import sandbox_runner

# Optional: read payload from GCS later if needed
# from google.cloud import storage

PROJECT_ID = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "ai-data-analyser"))
FILES_BUCKET = os.getenv("FILES_BUCKET", "ai-data-analyser-files")
PING_INTERVAL_SECONDS = int(os.getenv("SSE_PING_INTERVAL_SECONDS", "22"))
HARD_TIMEOUT_SECONDS = int(os.getenv("CHAT_HARD_TIMEOUT_SECONDS", "60"))
ORCH_IPC_MODE = os.getenv("ORCH_IPC_MODE", "base64").lower()


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
    try:
        if isinstance(payload_obj, dict):
            # Our payload emits: columns (dict), dataset meta, and sample_rows (list)
            cols = payload_obj.get("columns")
            if isinstance(cols, (list, dict)):
                # Truncate to a compact snippet for prompt
                schema_snippet = json.dumps(cols)[:500]
            sr = payload_obj.get("sample_rows")
            if isinstance(sr, list):
                sample_rows = sr[:10]
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
        chart_data = {"kind": "bar", "labels": [], "series": [{"label": "Count", "data": []}]}

        # Persist and done (no parquet or worker)
        yield _sse_format({"type": "persisting"})
        results_prefix = f"users/{uid}/sessions/{session_id}/results/{message_id}"
        uris = {
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
            "data": {"messageId": message_id, "chartData": chart_data, "tableSample": table[: min(len(table), 50)], "uris": uris},
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
            table = pq.read_table(pa.BufferReader(parquet_bytes))
            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, table.schema) as writer:
                writer.write_table(table)
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
        proc = subprocess.run(
            [os.environ.get("PYTHON_EXECUTABLE", sys.executable), worker_path],
            input=json.dumps({
                "code": code,
                "parquet_b64": parquet_b64,
                "arrow_ipc_b64": arrow_ipc_b64,
                "parquet_path": parquet_path,
                "ctx": {"row_limit": 200},
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
    except Exception as e:  # noqa: BLE001
        yield _sse_format({"type": "error", "data": {"code": "BAD_RESULT", "message": str(e)[:300]}})
        return

    table = result.get("table") or []
    metrics = result.get("metrics") or {}
    chart_data = result.get("chartData") or {}
    table_sample = table[: min(len(table), 50)]

    # summarizing (use fused pre-run summary)
    yield _sse_format({"type": "summarizing"})
    summary = pre_summary or ""

    # persist
    yield _sse_format({"type": "persisting"})
    results_prefix = f"users/{uid}/sessions/{session_id}/results/{message_id}"
    uris = {
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
    except Exception as e:  # noqa: BLE001
        yield _sse_format({"type": "error", "data": {"code": "PERSIST_FAILED", "message": str(e)[:400]}})
        return

    # Firestore message doc
    fs = firestore.Client(project=PROJECT_ID)
    msg_ref = (
        fs.collection("users")
        .document(uid)
        .collection("sessions")
        .document(session_id)
        .collection("messages")
        .document(message_id)
    )
    msg_ref.set({
        "role": "assistant",
        "question": question,
        "content": summary,
        "createdAt": datetime.now(timezone.utc),
        "status": "done",
        "uris": uris,
    })

    # done
    yield _sse_format({
        "type": "done",
        "data": {
            "messageId": message_id,
            "chartData": chart_data,
            "tableSample": table_sample,
            "uris": uris,
        },
    })
    # Close stream after final event (Option B)
    return


@functions_framework.http
def chat(request: Request) -> Response:
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": request.headers.get("Origin") or "http://localhost:3000",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-User-Id, X-Session-Id",
            "Access-Control-Max-Age": "3600",
            "Cache-Control": "no-store",
        }
        return ("", 204, headers)

    try:
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("sessionId") or request.headers.get("X-Session-Id")
        dataset_id = payload.get("datasetId")
        uid = request.headers.get("X-User-Id") or payload.get("uid")
        question = payload.get("question") or ""
        if not all([session_id, dataset_id, uid]):
            return (json.dumps({"error": "missing sessionId, datasetId, or uid"}), 400, {"Content-Type": "application/json"})

        origin = request.headers.get("Origin") or "http://localhost:3000"
        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": origin,
        }
        return Response(_events(session_id, dataset_id, uid, question), headers=headers, status=200)
    except Exception as e:  # noqa: BLE001
        return (json.dumps({"error": "internal error", "detail": str(e)[:500]}), 500, {"Content-Type": "application/json"})
