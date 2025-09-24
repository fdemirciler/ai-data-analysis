import json
import os
import time
from datetime import datetime, timezone
from typing import Generator, Iterable

import functions_framework
from flask import Request, Response
from google.cloud import firestore

# Optional: read payload from GCS later if needed
# from google.cloud import storage

PROJECT_ID = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "ai-data-analyser"))
PING_INTERVAL_SECONDS = int(os.getenv("SSE_PING_INTERVAL_SECONDS", "22"))


def _sse_format(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _heartbeat() -> str:
    return _sse_format({"type": "ping", "ts": datetime.now(timezone.utc).isoformat()})


def _events(session_id: str, dataset_id: str, uid: str) -> Iterable[str]:
    # received
    yield _sse_format({"type": "received", "data": {"sessionId": session_id, "datasetId": dataset_id}})

    # classifying (placeholder)
    yield _sse_format({"type": "classifying", "data": {"message": "Analyzing query intent..."}})

    # validate (placeholder)
    yield _sse_format({"type": "validating"})

    # run fast (placeholder)
    yield _sse_format({"type": "running_fast"})

    # summarize (placeholder)
    summary = f"Session {session_id}, dataset {dataset_id} processed at {datetime.now(timezone.utc).isoformat()}"
    yield _sse_format({"type": "summarizing"})

    # persist minimal message (placeholder)
    fs = firestore.Client(project=PROJECT_ID)
    msg_ref = fs.collection("users").document(uid).collection("sessions").document(session_id).collection("messages").document()
    msg_ref.set({
        "role": "assistant",
        "content": summary,
        "createdAt": datetime.now(timezone.utc)
    })
    yield _sse_format({"type": "persisting"})

    # done
    yield _sse_format({"type": "done", "data": {"message": "ok"}})

    # keep-alive loop if client keeps connection open
    last_ping = time.time()
    while True:
        now = time.time()
        if now - last_ping >= PING_INTERVAL_SECONDS:
            yield _heartbeat()
            last_ping = now
        time.sleep(1)


@functions_framework.http
def chat(request: Request) -> Response:
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": request.headers.get("Origin", "*"),
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "3600",
            "Cache-Control": "no-store",
        }
        return ("", 204, headers)

    try:
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("sessionId") or request.headers.get("X-Session-Id")
        dataset_id = payload.get("datasetId")
        uid = request.headers.get("X-User-Id") or payload.get("uid")
        if not all([session_id, dataset_id, uid]):
            return (json.dumps({"error": "missing sessionId, datasetId, or uid"}), 400, {"Content-Type": "application/json"})

        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": request.headers.get("Origin", "*"),
        }
        return Response(_events(session_id, dataset_id, uid), headers=headers, status=200)
    except Exception as e:  # noqa: BLE001
        return (json.dumps({"error": "internal error", "detail": str(e)[:500]}), 500, {"Content-Type": "application/json"})
