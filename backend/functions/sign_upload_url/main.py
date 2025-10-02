import os
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Tuple
import time

from google.cloud import storage
from google.cloud import firestore
import google.auth
from google.auth import impersonated_credentials
import google.auth.transport.requests
import firebase_admin
from firebase_admin import auth as fb_auth

MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB
FILES_BUCKET = os.getenv("FILES_BUCKET", "ai-data-analyser-files")
PROJECT_ID = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "ai-data-analyser"))
TTL_DAYS = int(os.getenv("TTL_DAYS", "1"))
RUNTIME_SERVICE_ACCOUNT = os.getenv("RUNTIME_SERVICE_ACCOUNT")
SIGNING_CREDS_TTL_SECONDS = int(os.getenv("SIGNING_CREDS_TTL_SECONDS", "3300"))  # ~55m

# Allowed origins (comma-separated). Default supports local dev and Firebase Hosting.
ALLOWED_ORIGINS = {
    o.strip()
    for o in (os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,https://ai-data-analyser.web.app,https://ai-data-analyser.firebaseapp.com",
    ) or "").split(",")
    if o.strip()
}

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


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    return origin in ALLOWED_ORIGINS


def _require_session_id(request) -> str:
    sid = request.headers.get("X-Session-Id") or request.args.get("sessionId")
    if not sid:
        raise ValueError("Missing X-Session-Id header")
    return sid


_CACHED_SIGNING_CREDS = None
_CACHED_EXPIRES_AT = 0.0


def _impersonated_signing_credentials(sa_email: str):
    """Create impersonated credentials for signing using IAM Credentials API.

    Requires that the runtime service account has roles/iam.serviceAccountTokenCreator
    on the target principal (can be itself). Also requires the
    iamcredentials.googleapis.com API to be enabled.
    """
    global _CACHED_SIGNING_CREDS, _CACHED_EXPIRES_AT

    # Cache hit
    now = time.time()
    if _CACHED_SIGNING_CREDS is not None and now < _CACHED_EXPIRES_AT:
        return _CACHED_SIGNING_CREDS

    if not sa_email:
        # Fall back to default credentials; will likely fail signing if no private key
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _CACHED_SIGNING_CREDS = creds
        _CACHED_EXPIRES_AT = now + SIGNING_CREDS_TTL_SECONDS
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
    _CACHED_EXPIRES_AT = now + SIGNING_CREDS_TTL_SECONDS
    return _CACHED_SIGNING_CREDS


try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()


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
    origin = request.headers.get("Origin") or ""
    if request.method == "OPTIONS":
        # CORS preflight
        if not _origin_allowed(origin):
            return ("Origin not allowed", 403, {"Content-Type": "text/plain"})
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            # Include lowercase variants to match Access-Control-Request-Headers
            "Access-Control-Allow-Headers": "Content-Type, content-type, Authorization, authorization, X-Session-Id, x-session-id",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)

    try:
        # Origin allowlist
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

        sid = _require_session_id(request)
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

        # Build signing credentials via impersonation so V4 signing works without a local private key.
        signing_creds = _impersonated_signing_credentials(RUNTIME_SERVICE_ACCOUNT)

        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=15),
            method="PUT",
            content_type=mime,
            credentials=signing_creds,
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
            "Access-Control-Allow-Origin": origin,
        }
        return (json.dumps(resp), 200, headers)

    except ValueError as ve:
        return (json.dumps({"error": str(ve)}), 400, {"Content-Type": "application/json"})
    except Exception as e:  # noqa: BLE001
        return (json.dumps({"error": "internal error", "detail": str(e)[:500]}), 500, {"Content-Type": "application/json"})

