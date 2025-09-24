import os
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Tuple

from google.cloud import storage
from google.cloud import firestore

MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB
FILES_BUCKET = os.getenv("FILES_BUCKET", "ai-data-analyser-files")
PROJECT_ID = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "ai-data-analyser"))
TTL_DAYS = int(os.getenv("TTL_DAYS", "1"))

ALLOWED_MIME = {
    "text/csv": ".csv",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}
ALLOWED_EXT = {".csv", ".xls", ".xlsx"}


def _ext_from_filename_or_type(filename: str, mime: str) -> str:
    ext = os.path.splitext(filename)[1].lower() if filename else ""
    if ext in ALLOWED_EXT:
        return ext
    return ALLOWED_MIME.get(mime, "")


def _require_headers(request) -> Tuple[str, str]:
    uid = request.headers.get("X-User-Id")
    sid = request.headers.get("X-Session-Id")
    if not uid or not sid:
        raise ValueError("Missing X-User-Id or X-Session-Id header")
    return uid, sid


def sign_upload_url(request):
    """HTTP Cloud Function entrypoint.

    Query params:
    - filename
    - size (bytes)
    - type (mime)
    Headers:
    - X-User-Id
    - X-Session-Id
    """
    if request.method == "OPTIONS":
        # CORS preflight
        headers = {
            "Access-Control-Allow-Origin": request.headers.get("Origin", "*"),
            "Access-Control-Allow-Methods": "PUT, GET, HEAD, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, x-goog-meta-*",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    try:
        uid, sid = _require_headers(request)
        filename = request.args.get("filename", "")
        size = int(request.args.get("size", "0"))
        mime = request.args.get("type", "")

        if not filename or not mime:
            return (json.dumps({"error": "filename and type are required"}), 400, {"Content-Type": "application/json"})
        if size <= 0 or size > MAX_FILE_BYTES:
            return (json.dumps({"error": "file too large (max 20MB)"}), 400, {"Content-Type": "application/json"})

        ext = _ext_from_filename_or_type(filename, mime)
        if ext not in ALLOWED_EXT:
            return (json.dumps({"error": "unsupported file type"}), 400, {"Content-Type": "application/json"})

        dataset_id = str(uuid.uuid4())
        object_path = f"users/{uid}/sessions/{sid}/datasets/{dataset_id}/raw/input{ext}"

        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(FILES_BUCKET)
        blob = bucket.blob(object_path)

        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=15),
            method="PUT",
            content_type=mime,
        )

        # Pre-create dataset doc as awaiting upload (optional, helps UI)
        fs = firestore.Client(project=PROJECT_ID)
        ttl_at = datetime.now(timezone.utc) + timedelta(days=TTL_DAYS)
        fs.document("users", uid, "sessions", sid, "datasets", dataset_id).set(
            {
                "status": "awaiting_upload",
                "rawUri": f"gs://{FILES_BUCKET}/{object_path}",
                "createdAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc),
                "ttlAt": ttl_at,
            },
            merge=True,
        )

        resp = {
            "url": url,
            "datasetId": dataset_id,
            "storagePath": object_path,
        }
        headers = {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": request.headers.get("Origin", "*"),
        }
        return (json.dumps(resp), 200, headers)

    except ValueError as ve:
        return (json.dumps({"error": str(ve)}), 400, {"Content-Type": "application/json"})
    except Exception as e:  # noqa: BLE001
        return (json.dumps({"error": "internal error", "detail": str(e)[:500]}), 500, {"Content-Type": "application/json"})
