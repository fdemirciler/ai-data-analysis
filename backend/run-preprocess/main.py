import os
import json
import logging
import base64
import io
import time
from concurrent.futures import ThreadPoolExecutor
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
_process_bytes_to_artifacts = None  # type: ignore

def _get_engine() -> str:
    eng = os.getenv("PREPROCESS_ENGINE", "polars").strip().lower()
    return "polars" if eng == "polars" else "pandas"

def get_process_file_to_artifacts():
    """Import and cache process_file_to_artifacts lazily.

    Tries package-relative import first, then absolute import for script mode.
    Raises the underlying exception if imports fail, and logs for visibility.
    """
    global _process_file_to_artifacts
    if _process_file_to_artifacts is not None:
        return _process_file_to_artifacts
    engine = _get_engine()
    # Prefer polars adapter when requested, else default to pandas adapter
    try:
        if engine == "polars":
            try:
                from .pipeline_adapter_polars import process_file_to_artifacts as _fn  # type: ignore
            except Exception:
                from pipeline_adapter_polars import process_file_to_artifacts as _fn  # type: ignore
            logging.info("preprocess engine: polars")
        else:
            raise ImportError("force_pandas")
    except Exception:
        # Fallback to pandas adapter
        try:
            from .pipeline_adapter import process_file_to_artifacts as _fn  # type: ignore
        except Exception:
            from pipeline_adapter import process_file_to_artifacts as _fn  # type: ignore
        logging.info("preprocess engine: pandas (fallback)")
    _process_file_to_artifacts = _fn
    return _fn


def get_process_bytes_to_artifacts():
    """Import and cache process_bytes_to_artifacts lazily."""
    global _process_bytes_to_artifacts
    if _process_bytes_to_artifacts is not None:
        return _process_bytes_to_artifacts
    engine = _get_engine()
    try:
        if engine == "polars":
            try:
                from .pipeline_adapter_polars import process_bytes_to_artifacts as _fn  # type: ignore
            except Exception:
                from pipeline_adapter_polars import process_bytes_to_artifacts as _fn  # type: ignore
            logging.info("preprocess engine: polars")
        else:
            raise ImportError("force_pandas")
    except Exception:
        try:
            from .pipeline_adapter import process_bytes_to_artifacts as _fn  # type: ignore
        except Exception:
            from pipeline_adapter import process_bytes_to_artifacts as _fn  # type: ignore
        logging.info("preprocess engine: pandas (fallback)")
    _process_bytes_to_artifacts = _fn
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
    # Read raw body and attempt to support multiple delivery shapes:
    # 1) CloudEvents structured: { "data": { "bucket": ..., "name": ... }, ... }
    # 2) CloudEvents binary: body is the data object itself
    # 3) Pub/Sub push: { "message": { "data": base64(json) }, ... }
    # 4) GCS notification compatibility: top-level { "bucket": ..., "name": ... }
    envelope: dict = {}
    try:
        body_bytes = await request.body()
        body_text = body_bytes.decode("utf-8") if body_bytes else "{}"
        envelope = json.loads(body_text or "{}") if body_text else {}
    except Exception as e:
        logging.warning("Invalid JSON for Eventarc request: %s", e)
        envelope = {}

    data = None
    t0 = time.monotonic()

    # Structured CloudEvent
    if isinstance(envelope, dict) and "data" in envelope and isinstance(envelope["data"], dict):
        data = envelope["data"]

    # Pub/Sub push format
    if data is None and isinstance(envelope, dict) and "message" in envelope:
        try:
            msg = envelope.get("message", {})
            b64 = msg.get("data")
            if isinstance(b64, str):
                decoded = base64.b64decode(b64 + "==")
                inner = json.loads(decoded.decode("utf-8"))
                data = inner.get("data") if isinstance(inner, dict) and "data" in inner else inner
        except Exception as e:
            logging.warning("Failed to decode Pub/Sub envelope: %s", e)

    # GCS notification compatibility or binary CE body
    if data is None and isinstance(envelope, dict):
        if "bucket" in envelope or "name" in envelope or "objectId" in envelope:
            data = envelope

    if not isinstance(data, dict):
        logging.warning("Event parsing failed; envelope keys=%s headers.ce-type=%s", list(envelope.keys()) if isinstance(envelope, dict) else type(envelope), request.headers.get("ce-type"))
        return Response(status_code=204)

    bucket = data.get("bucket")
    name = data.get("name") or data.get("objectId") or data.get("object")

    if not bucket or not name:
        logging.warning("Missing bucket/name after normalization: %s", data)
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
        # 1) Download raw into memory
        raw_blob = storage_client.bucket(bucket).blob(name)
        raw_bytes = raw_blob.download_as_bytes()
        kind = "excel" if is_xlsx else "csv"
        t_download = time.monotonic()

        # 2) Optional manual header-row override from GCS metadata (preferred) or env fallback
        header_row_override = None
        try:
            prefix = f"users/{uid}/sessions/{sid}/datasets/{dataset_id}"
            override_blob = storage_client.bucket(bucket).blob(f"{prefix}/metadata/preprocess_overrides.json")
            if override_blob.exists(storage_client):
                override_obj = json.loads(override_blob.download_as_text())
                val = override_obj.get("header_row_index")
                if isinstance(val, int):
                    header_row_override = val
        except Exception as e:
            logging.warning("override_read_failed: %s", e)

        if header_row_override is None:
            try:
                env_val = os.getenv("PREPROCESS_HEADER_ROW_OVERRIDE")
                if env_val is not None and str(env_val).strip() != "":
                    header_row_override = int(str(env_val).strip())
            except Exception:
                pass

        # 3) Run pipeline adapter (bytes variant; lazy import on first use)
        result = get_process_bytes_to_artifacts()( 
            raw_bytes,
            kind,
            sample_rows_for_llm=50,
            metric_rename_heuristic=False,
            header_row_override=header_row_override,
        )
        t_process = time.monotonic()

        # 3) Write artifacts to GCS under dataset prefix (in parallel)
        prefix = f"users/{uid}/sessions/{sid}/datasets/{dataset_id}"
        cleaned_path = f"{prefix}/cleaned/cleaned.parquet"
        payload_path = f"{prefix}/metadata/payload.json"
        report_path = f"{prefix}/reports/cleaning_report.json"

        # Build in-memory parquet
        parquet_buf = io.BytesIO()
        result.cleaned_df.to_parquet(parquet_buf, engine="pyarrow", index=False)
        parquet_size = parquet_buf.getbuffer().nbytes
        parquet_buf.seek(0)
        t_build = time.monotonic()

        payload_data = json.dumps(result.payload, ensure_ascii=False).encode("utf-8")
        report_data = json.dumps(result.cleaning_report, ensure_ascii=False).encode("utf-8")

        bkt = storage_client.bucket(bucket)
        cleaned_blob = bkt.blob(cleaned_path)
        payload_blob = bkt.blob(payload_path)
        report_blob = bkt.blob(report_path)

        # Upload three artifacts in parallel
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = []
            futs.append(ex.submit(cleaned_blob.upload_from_file, parquet_buf, size=parquet_size, content_type="application/octet-stream"))
            futs.append(ex.submit(payload_blob.upload_from_string, payload_data, content_type="application/json; charset=utf-8"))
            futs.append(ex.submit(report_blob.upload_from_string, report_data, content_type="application/json; charset=utf-8"))
            for f in futs:
                f.result()
        t_uploads = time.monotonic()

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
        t_firestore = time.monotonic()

        logging.info(json.dumps({
            "event": "preprocess_complete",
            "uid": uid,
            "sid": sid,
            "datasetId": dataset_id,
            "rows": result.rows,
            "columns": result.columns,
            "cleanedUri": cleaned_uri,
            "payloadUri": payload_uri,
            "reportUri": report_uri,
        }))

        # header detection telemetry (v2 fields are additive; guard if missing)
        try:
            header_info = (result.payload or {}).get("header_info", {})
            conf = float(header_info.get("confidence") or 0.0)
            method = header_info.get("method") or "unknown"
            hrow = int(header_info.get("header_row_index") or -1)
            is_transposed = bool(header_info.get("is_transposed") or False)
            lookahead = int(os.getenv("PREPROCESS_HEADER_LOOKAHEAD", "12"))
            low_thr = float(os.getenv("HEADER_LOW_CONFIDENCE_THRESHOLD", "0.4"))
            low_conf = conf < low_thr
            logging.info(json.dumps({
                "event": "header_detection",
                "uid": uid,
                "sid": sid,
                "datasetId": dataset_id,
                "engine": _get_engine(),
                "header_row_index": hrow,
                "confidence": round(conf, 3),
                "method": method,
                "is_transposed": is_transposed,
                "lookahead": lookahead,
                "low_confidence": low_conf,
            }))
        except Exception as e:
            logging.warning("header_detection_log_failed: %s", e)
        # timings
        timings = {
            "event": "preprocess_timings",
            "uid": uid,
            "sid": sid,
            "datasetId": dataset_id,
            "download_s": round(t_download - t0, 3),
            "process_s": round(t_process - t_download, 3),
            "build_parquet_s": round(t_build - t_process, 3),
            "uploads_s": round(t_uploads - t_build, 3),
            "firestore_s": round(t_firestore - t_uploads, 3),
            "total_s": round(t_firestore - t0, 3),
        }
        logging.info(json.dumps(timings))
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
    # This block is for local development or when run directly.
    # Cloud Run will provide the PORT environment variable.
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)