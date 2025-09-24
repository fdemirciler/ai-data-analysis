import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import FastAPI, Request, Response

# Optional: import google clients (not used until wired)
try:
    from google.cloud import storage  # type: ignore
    from google.cloud import firestore  # type: ignore
    import google.cloud.logging as cloud_logging  # type: ignore
except Exception:  # pragma: no cover - allow local runs without GCP libs installed
    storage = None
    firestore = None
    cloud_logging = None  # type: ignore

app = FastAPI(title="Preprocess Service", version="0.1.0")

FILES_BUCKET = os.getenv("FILES_BUCKET", "ai-data-analyser-files")
PROJECT_ID = os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "ai-data-analyser"))
TTL_DAYS = int(os.getenv("TTL_DAYS", "1"))

def _setup_cloud_logging() -> None:
    """Configure Google Cloud Logging handler if available.

    In Cloud Run, this attaches a handler to the root logger, enabling structured
    logs in Cloud Logging. Fallback to std logging if the client is unavailable.
    """
    if cloud_logging is None:
        return
    try:
        client = cloud_logging.Client(project=PROJECT_ID)
        client.setup_logging()  # attaches handler to root logger
        logging.getLogger().setLevel(logging.INFO)
        logging.info("cloud-logging: configured")
    except Exception as e:
        logging.warning("cloud-logging: setup failed: %s", e)


# Configure logging at startup time
@app.on_event("startup")
async def _on_startup() -> None:  # pragma: no cover
    _setup_cloud_logging()

"""Lazy import loader for pipeline_adapter.

We avoid importing heavy data libs (pandas/pyarrow) at module import time so
the Cloud Run container can start and bind to PORT quickly. The actual import
occurs on first use inside the request handler.
"""
_process_file_to_artifacts = None  # type: ignore

def get_process_file_to_artifacts():
    """Import and cache process_file_to_artifacts lazily.

    Tries package-relative import first, then absolute import for script mode.
    Raises the underlying exception if imports fail, and logs for visibility.
    """
    global _process_file_to_artifacts
    if _process_file_to_artifacts is not None:
        return _process_file_to_artifacts
    try:
        from .pipeline_adapter import process_file_to_artifacts as _fn  # type: ignore
    except Exception:
        try:
            from pipeline_adapter import process_file_to_artifacts as _fn  # type: ignore
        except Exception as e:  # pragma: no cover - surfaced in logs at runtime
            logging.exception("Failed to import pipeline_adapter: %s", e)
            raise
    _process_file_to_artifacts = _fn
    return _fn


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "bucket": FILES_BUCKET, "project": PROJECT_ID}


def _parse_object_path(name: str) -> Optional[Tuple[str, str, str]]:
    """Parse gs object path to (uid, sid, datasetId).
    Expected structure:
    users/{uid}/sessions/{sid}/datasets/{datasetId}/raw/input.csv|xlsx
    """
    try:
        parts = name.split("/")
        i = parts.index("users")
        uid = parts[i + 1]
        assert parts[i + 2] == "sessions"
        sid = parts[i + 3]
        assert parts[i + 4] == "datasets"
        dataset_id = parts[i + 5]
        assert parts[i + 6] == "raw"
        return uid, sid, dataset_id
    except Exception:
        return None


@app.post("/eventarc")
async def handle_eventarc(request: Request) -> Response:
    """Handle Eventarc GCS finalize events.

    Accepts CloudEvent-like body with `data.bucket` and `data.name`.
    Ignores events that are not under `/raw/` or are not CSV/XLSX.
    """
    try:
        envelope = await request.json()
    except Exception:
        logging.warning("Invalid JSON for Eventarc request")
        return Response(status_code=204)

    data = envelope.get("data") or {}
    bucket = data.get("bucket")
    name = data.get("name")

    if not bucket or not name:
        logging.warning("Missing bucket/name in event data")
        return Response(status_code=204)

    # Only react to raw uploads (csv/xlsx)
    is_raw = "/raw/" in name
    is_csv = name.lower().endswith(".csv")
    is_xlsx = name.lower().endswith(".xlsx") or name.lower().endswith(".xls")
    if not (is_raw and (is_csv or is_xlsx)):
        return Response(status_code=204)

    ids = _parse_object_path(name)
    if not ids:
        logging.warning("Object path does not match expected pattern: %s", name)
        return Response(status_code=204)

    uid, sid, dataset_id = ids
    logging.info("Preprocess trigger: bucket=%s name=%s uid=%s sid=%s dataset=%s", bucket, name, uid, sid, dataset_id)
    # Initialize clients lazily
    if storage is None or firestore is None:
        logging.error("GCP clients not available in runtime environment")
        return Response(status_code=500)

    storage_client = storage.Client(project=PROJECT_ID)
    firestore_client = firestore.Client(project=PROJECT_ID)

    try:
        # 1) Download raw to /tmp
        raw_blob = storage_client.bucket(bucket).blob(name)
        ext = ".xlsx" if is_xlsx else ".csv"
        tmp_raw_path = f"/tmp/{uid}_{sid}_{dataset_id}_raw{ext}"
        raw_blob.download_to_filename(tmp_raw_path)

        # 2) Run pipeline adapter (lazy import on first use)
        result = get_process_file_to_artifacts()( 
            tmp_raw_path,
            sample_rows_for_llm=50,
            metric_rename_heuristic=False,
        )

        # 3) Write artifacts to GCS under dataset prefix
        prefix = f"users/{uid}/sessions/{sid}/datasets/{dataset_id}"
        cleaned_path = f"{prefix}/cleaned/cleaned.parquet"
        payload_path = f"{prefix}/metadata/payload.json"
        report_path = f"{prefix}/reports/cleaning_report.json"

        # 3a) Save cleaned parquet to /tmp and upload
        tmp_cleaned_path = f"/tmp/{uid}_{sid}_{dataset_id}_cleaned.parquet"
        # Ensure pyarrow engine
        result.cleaned_df.to_parquet(tmp_cleaned_path, engine="pyarrow", index=False)
        storage_client.bucket(bucket).blob(cleaned_path).upload_from_filename(
            tmp_cleaned_path, content_type="application/octet-stream"
        )

        # 3b) Upload payload.json
        payload_data = json.dumps(result.payload, ensure_ascii=False).encode("utf-8")
        storage_client.bucket(bucket).blob(payload_path).upload_from_string(
            payload_data, content_type="application/json; charset=utf-8"
        )

        # 3c) Upload cleaning_report.json
        report_data = json.dumps(result.cleaning_report, ensure_ascii=False).encode("utf-8")
        storage_client.bucket(bucket).blob(report_path).upload_from_string(
            report_data, content_type="application/json; charset=utf-8"
        )

        cleaned_uri = f"gs://{bucket}/{cleaned_path}"
        payload_uri = f"gs://{bucket}/{payload_path}"
        report_uri = f"gs://{bucket}/{report_path}"

        # 4) Update Firestore dataset doc
        ttl_at = datetime.now(timezone.utc) + timedelta(days=TTL_DAYS)
        doc_ref = firestore_client.document(
            "users", uid, "sessions", sid, "datasets", dataset_id
        )
        doc_ref.set(
            {
                "rawUri": f"gs://{bucket}/{name}",
                "cleanedUri": cleaned_uri,
                "payloadUri": payload_uri,
                "reportUri": report_uri,
                "rows": result.rows,
                "columns": result.columns,
                "status": "ready",
                "updatedAt": datetime.now(timezone.utc),
                "ttlAt": ttl_at,
            },
            merge=True,
        )

        logging.info(
            json.dumps(
                {
                    "event": "preprocess_complete",
                    "uid": uid,
                    "sid": sid,
                    "datasetId": dataset_id,
                    "rows": result.rows,
                    "columns": result.columns,
                    "cleanedUri": cleaned_uri,
                    "payloadUri": payload_uri,
                    "reportUri": report_uri,
                }
            )
        )
        return Response(status_code=204)

    except Exception as e:  # noqa: BLE001 (broad for last-resort error path)
        logging.exception("Preprocess failed: %s", e)
        try:
            ttl_at = datetime.now(timezone.utc) + timedelta(days=TTL_DAYS)
            firestore_client.document(
                "users", uid, "sessions", sid, "datasets", dataset_id
            ).set(
                {
                    "status": "error",
                    "errorMessage": str(e)[:2000],
                    "updatedAt": datetime.now(timezone.utc),
                    "ttlAt": ttl_at,
                },
                merge=True,
            )
        except Exception:
            logging.warning("Failed to write error status to Firestore")
        return Response(status_code=500)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
