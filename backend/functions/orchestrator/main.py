import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Generator, Iterable

import functions_framework
from flask import Request, Response
from google.cloud import firestore

# Optional: read payload from GCS later if needed
# from google.cloud import storage

PROJECT_ID = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "ai-data-analyser"))
PING_INTERVAL_SECONDS = int(os.getenv("SSE_PING_INTERVAL_SECONDS", "22"))
HARD_TIMEOUT_SECONDS = int(os.getenv("CHAT_HARD_TIMEOUT_SECONDS", "60"))


def _sse_format(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _heartbeat() -> str:
    return _sse_format({"type": "ping", "ts": datetime.now(timezone.utc).isoformat()})


def _events(session_id: str, dataset_id: str, uid: str) -> Iterable[str]:
    # received
    yield _sse_format({"type": "received", "data": {"sessionId": session_id, "datasetId": dataset_id}})

    # validating (placeholder)
    yield _sse_format({"type": "validating"})

    # generating_code (placeholder for LLM codegen)
    yield _sse_format({"type": "generating_code"})

    # running_fast (placeholder for sandboxed execution)
    yield _sse_format({"type": "running_fast"})

    # summarizing (placeholder for Gemini summary)
    summary = (
        f"Session {session_id}, dataset {dataset_id} processed at "
        f"{datetime.now(timezone.utc).isoformat()}"
    )
    yield _sse_format({"type": "summarizing"})

    # Build stub outputs for Milestone 1
    message_id = str(uuid.uuid4())
    table_sample = [
        {"category": "A", "value": 1},
        {"category": "B", "value": 2},
        {"category": "C", "value": 3},
    ]
    chart_data = {
        "kind": "bar",
        "labels": ["A", "B", "C"],
        "series": [
            {"label": "Value", "data": [1, 2, 3]}
        ],
        # optional options placeholder; frontend may ignore
        "options": {"responsive": True}
    }

    # persist minimal message (placeholder)
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
        "content": summary,
        "createdAt": datetime.now(timezone.utc),
        "status": "done",
    })
    yield _sse_format({"type": "persisting"})

    # done with inline chartData/tableSample and placeholder URIs
    yield _sse_format({
        "type": "done",
        "data": {
            "messageId": message_id,
            "chartData": chart_data,
            "tableSample": table_sample,
            "uris": {
                "table": None,
                "metrics": None,
                "chartData": None,
                "summary": None,
            },
        },
    })

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
            "Access-Control-Allow-Origin": request.headers.get("Origin") or "http://localhost:3000",
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

        origin = request.headers.get("Origin") or "http://localhost:3000"
        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": origin,
        }
        return Response(_events(session_id, dataset_id, uid), headers=headers, status=200)
    except Exception as e:  # noqa: BLE001
        return (json.dumps({"error": "internal error", "detail": str(e)[:500]}), 500, {"Content-Type": "application/json"})
