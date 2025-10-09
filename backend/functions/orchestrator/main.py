import json
import os
import time
import uuid
import subprocess
import sys
import io
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
import analysis_toolkit
import aliases
from google.api_core import exceptions as gax_exceptions  # type: ignore
import logging
from functools import lru_cache

# Configuration
PROJECT_ID = os.getenv("GCP_PROJECT", "ai-data-analyser")
FILES_BUCKET = os.getenv("FILES_BUCKET", "ai-data-analyser-files")
PING_INTERVAL_SECONDS = int(os.getenv("SSE_PING_INTERVAL_SECONDS", "22"))
HARD_TIMEOUT_SECONDS = int(os.getenv("CHAT_HARD_TIMEOUT_SECONDS", "60"))
REPAIR_TIMEOUT_SECONDS = int(os.getenv("CHAT_REPAIR_TIMEOUT_SECONDS", "30"))
ORCH_IPC_MODE = os.getenv("ORCH_IPC_MODE", "base64").lower()
RUNTIME_SERVICE_ACCOUNT = os.getenv("RUNTIME_SERVICE_ACCOUNT")

# Smart dispatcher flags
FASTPATH_ENABLED = os.getenv("FASTPATH_ENABLED", "1").lower() not in ("0", "false", "no")
FALLBACK_ENABLED = os.getenv("FALLBACK_ENABLED", "1").lower() not in ("0", "false", "no")
CODE_RECONSTRUCT_ENABLED = os.getenv("CODE_RECONSTRUCT_ENABLED", "1").lower() not in ("0", "false", "no")
MIN_FASTPATH_CONFIDENCE = float(os.getenv("MIN_FASTPATH_CONFIDENCE", "0.65"))
CLASSIFIER_TIMEOUT_SECONDS = int(os.getenv("CLASSIFIER_TIMEOUT_SECONDS", "8"))
MAX_FASTPATH_ROWS = int(os.getenv("MAX_FASTPATH_ROWS", "50000"))
FORCE_FALLBACK_MIN_ROWS = int(os.getenv("FORCE_FALLBACK_MIN_ROWS", "500000"))
MAX_CHART_POINTS = int(os.getenv("MAX_CHART_POINTS", "500"))
TOOLKIT_VERSION = int(os.getenv("TOOLKIT_VERSION", str(getattr(analysis_toolkit, "TOOLKIT_VERSION", 1))))
MIRROR_COMMAND_TO_FIRESTORE = os.getenv("MIRROR_COMMAND_TO_FIRESTORE", "0").lower() in ("1", "true", "yes")
CODEGEN_TIMEOUT_SECONDS = int(os.getenv("CODEGEN_TIMEOUT_SECONDS", "30"))

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
    dataset_meta = payload_obj.get("dataset", {}) or {}
    dataset_rows = int(dataset_meta.get("rows") or 0)
    column_names = list(dataset_meta.get("column_names") or (payload_obj.get("columns", {}) or {}).keys())

    # --- Optional: Unified Presentational Code (Show Code) ---
    @lru_cache(maxsize=32)
    def _cached_presentational_code(mid: str, ctx_json: str, schema: str, style: str) -> str:
        try:
            ctx = json.loads(ctx_json)
        except Exception:
            ctx = {}
        return gemini_client.generate_presentational_code(ctx, schema, style=style)

    try:
        if CODE_RECONSTRUCT_ENABLED:
            show_req = gemini_client.is_show_code_request(question)
            if isinstance(show_req, dict) and show_req.get("is_code_request") is True:
                results_prefix = f"users/{uid}/sessions/{session_id}/results/"
                latest_strategy_blob = None
                for blob in storage_client.list_blobs(FILES_BUCKET, prefix=results_prefix):
                    if blob.name.endswith("/strategy.json"):
                        if latest_strategy_blob is None or (getattr(blob, "updated", None) and blob.updated > latest_strategy_blob.updated):
                            latest_strategy_blob = blob
                if latest_strategy_blob is None:
                    yield _sse_format({"type": "error", "data": {"code": "NO_PREV_ANALYSIS", "message": "No previous analysis found to reconstruct."}})
                    return
                strategy_obj = json.loads(latest_strategy_blob.download_as_text()) or {}
                result_dir = latest_strategy_blob.name.rsplit("/", 1)[0]
                message_id_prev = result_dir.split("/")[-1]

                context: dict = {}
                if isinstance(strategy_obj.get("command"), dict):
                    context = {"command": strategy_obj.get("command")}
                elif isinstance(strategy_obj.get("question"), str) and strategy_obj.get("question").strip():
                    context = {"question": strategy_obj.get("question")}
                else:
                    # Back-compat: try command.json
                    cmd_blob = storage_client.bucket(FILES_BUCKET).blob(f"{result_dir}/command.json")
                    if cmd_blob.exists():
                        try:
                            context = {"command": json.loads(cmd_blob.download_as_text())}
                        except Exception:
                            context = {}

                if not context:
                    yield _sse_format({"type": "error", "data": {"code": "NO_CONTEXT", "message": "Could not find the context for the previous analysis."}})
                    return

                style = os.getenv("PRESENTATIONAL_CODE_STYLE", "educational")
                ctx_json = json.dumps(context, ensure_ascii=False, sort_keys=True)
                code_text = _cached_presentational_code(message_id_prev, ctx_json, schema_snippet, style)
                yield _sse_format({
                    "type": "code",
                    "data": {"language": "python", "text": code_text, "warnings": [], "source": "presentation"}
                })
                return
    except Exception:
        # Non-fatal; continue with normal flow
        pass

    # --- Smart Dispatcher: Fast-path Classification ---
    if FASTPATH_ENABLED and (FORCE_FALLBACK_MIN_ROWS <= 0 or dataset_rows < FORCE_FALLBACK_MIN_ROWS):
        # Build hinting block
        hinting = json.dumps({
            "aliases": getattr(aliases, "ALIASES", {}),
            "dataset_summary": payload_obj.get("dataset_summary") or payload_obj.get("dataset", {}),
            "columns": column_names[:50],
        })

        classification = None
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(
                    gemini_client.classify_intent,
                    question,
                    schema_snippet,
                    sample_rows,
                    analysis_toolkit.TOOLS_SPEC,
                    hinting,
                )
                remaining = CLASSIFIER_TIMEOUT_SECONDS
                while True:
                    try:
                        classification = fut.result(timeout=min(remaining, 2))
                        break
                    except FuturesTimeout:
                        yield _sse_format({"type": "still_working"})
                        remaining -= 2
                        if remaining <= 0:
                            raise
        except FuturesTimeout:
            classification = {"intent": "UNKNOWN", "params": {}, "confidence": 0.0}
        except Exception:
            classification = {"intent": "UNKNOWN", "params": {}, "confidence": 0.0}

        # Canonicalize tool name and params to router intents
        raw_intent = (classification or {}).get("intent") or "UNKNOWN"
        raw_params = (classification or {}).get("params") or {}
        confidence = float((classification or {}).get("confidence") or 0.0)

        # Map tool names to canonical intents
        name_map = {
            "run_aggregation": "AGGREGATE",
            "run_variance": "VARIANCE",
            "run_filter_and_sort": "FILTER_SORT",
            "run_describe": "DESCRIBE",
        }
        intent = name_map.get(str(raw_intent), str(raw_intent).upper())

        # Convert snake_case params to existing camelCase where needed
        params = dict(raw_params)
        if intent == "VARIANCE":
            if "period_a" in params and "periodA" not in params:
                params["periodA"] = params.get("period_a")
            if "period_b" in params and "periodB" not in params:
                params["periodB"] = params.get("period_b")

        # Parameter validation and resolution
        def _validate_and_resolve(i: str, p: dict) -> tuple[bool, dict]:
            resolved = dict(p)
            try:
                if i == "AGGREGATE":
                    resolved["dimension"] = aliases.resolve_column(p.get("dimension"), column_names) or p.get("dimension")
                    resolved["metric"] = aliases.resolve_column(p.get("metric"), column_names) or p.get("metric")
                    return bool(resolved.get("dimension") and resolved.get("metric") and p.get("func")), resolved
                if i == "VARIANCE":
                    resolved["dimension"] = aliases.resolve_column(p.get("dimension"), column_names) or p.get("dimension")
                    resolved["periodA"] = aliases.resolve_column(p.get("periodA"), column_names) or p.get("periodA")
                    resolved["periodB"] = aliases.resolve_column(p.get("periodB"), column_names) or p.get("periodB")
                    return bool(resolved.get("dimension") and resolved.get("periodA") and resolved.get("periodB")), resolved
                if i == "FILTER_SORT":
                    resolved["sort_col"] = aliases.resolve_column(p.get("sort_col"), column_names) or p.get("sort_col")
                    if p.get("filter_col"):
                        resolved["filter_col"] = aliases.resolve_column(p.get("filter_col"), column_names) or p.get("filter_col")
                    return bool(resolved.get("sort_col")), resolved
                if i == "DESCRIBE":
                    return True, resolved
            except Exception:
                return False, resolved
            return False, resolved

        params_ok, resolved_params = _validate_and_resolve(intent, params)

        # Soft-accept logic
        soft_threshold = max(0.0, MIN_FASTPATH_CONFIDENCE - 0.15)
        is_fastpath_candidate = (intent in {"AGGREGATE", "VARIANCE", "FILTER_SORT", "DESCRIBE"}) and (
            confidence >= MIN_FASTPATH_CONFIDENCE or (params_ok and confidence >= soft_threshold)
        )

        # Optional SSE for debugging (no data rows logged)
        if os.getenv("LOG_CLASSIFIER_RESPONSE") == "1":
            try:
                yield _sse_format({
                    "type": "classification_result",
                    "data": {"intent": intent, "params": resolved_params, "confidence": confidence}
                })
            except Exception:
                pass
        # Structured log for classifier outcome (no sample rows)
        try:
            logging.info(json.dumps({
                "event": "classifier_result",
                "intent": intent,
                "confidence": confidence,
                "params": resolved_params,
                "dataset_rows": dataset_rows,
            }))
        except Exception:
            pass

        if is_fastpath_candidate:
            try:
                logging.info(json.dumps({
                    "event": "router_decision",
                    "strategy": "fastpath",
                    "reason": "accepted",
                    "intent": intent,
                    "confidence": confidence,
                }))
            except Exception:
                pass
            yield _sse_format({"type": "generating_code"})
            yield _sse_format({"type": "running_fast"})
            parquet_gcs_path = f"users/{uid}/sessions/{session_id}/datasets/{dataset_id}/cleaned/cleaned.parquet"
            try:
                parquet_blob = bucket.blob(parquet_gcs_path)
                parquet_bytes = parquet_blob.download_as_bytes()
            except Exception as e:
                yield _sse_format({"type": "error", "data": {"code": "DATA_READ_FAILED", "message": str(e)}})
            else:
                try:
                    # Determine needed columns
                    needed_cols = None
                    if intent == "AGGREGATE":
                        dim = aliases.resolve_column(params.get("dimension"), column_names) or params.get("dimension")
                        met = aliases.resolve_column(params.get("metric"), column_names) or params.get("metric")
                        needed_cols = [c for c in [dim, met] if c]
                    elif intent == "VARIANCE":
                        dim = aliases.resolve_column(params.get("dimension"), column_names) or params.get("dimension")
                        a = aliases.resolve_column(params.get("periodA"), column_names) or params.get("periodA")
                        b = aliases.resolve_column(params.get("periodB"), column_names) or params.get("periodB")
                        needed_cols = [c for c in [dim, a, b] if c]
                    elif intent == "FILTER_SORT":
                        sort_col = aliases.resolve_column(params.get("sort_col"), column_names) or params.get("sort_col")
                        fcol = params.get("filter_col")
                        fcol = aliases.resolve_column(fcol, column_names) if fcol else fcol
                        needed_cols = [c for c in [sort_col, fcol] if c]

                    if needed_cols:
                        df = pd.read_parquet(io.BytesIO(parquet_bytes), columns=needed_cols)
                    else:
                        df = pd.read_parquet(io.BytesIO(parquet_bytes))
                    if MAX_FASTPATH_ROWS > 0 and len(df) > MAX_FASTPATH_ROWS:
                        df = df.head(MAX_FASTPATH_ROWS)

                    # Execute
                    if intent == "AGGREGATE":
                        res_df = analysis_toolkit.run_aggregation(df, dim, met, resolved_params.get("func", params.get("func", "sum")))
                    elif intent == "VARIANCE":
                        res_df = analysis_toolkit.run_variance(df, dim, a, b)
                    elif intent == "FILTER_SORT":
                        res_df = analysis_toolkit.run_filter_and_sort(
                            df,
                            sort_col=sort_col,
                            ascending=bool(resolved_params.get("ascending", params.get("ascending", False))),
                            limit=int((resolved_params.get("limit") or params.get("limit") or 50)),
                            filter_col=fcol,
                            filter_val=resolved_params.get("filter_val", params.get("filter_val")),
                        )
                    else:
                        res_df = analysis_toolkit.run_describe(df)

                    summary_obj = gemini_client.format_final_response(question, res_df)
                    summary_text = summary_obj.get("summary") or ""
                    table_rows = res_df.head(50).to_dict(orient="records")
                    metrics = {"rows": int(getattr(res_df, "shape", [0, 0])[0] or 0),
                               "columns": int(getattr(res_df, "shape", [0, 0])[1] or 0)}
                    chart_data = {}

                    yield _sse_format({"type": "persisting"})
                    message_id = str(uuid.uuid4())
                    results_prefix = f"users/{uid}/sessions/{session_id}/results/{message_id}"
                    table_path = f"{results_prefix}/fastpath_table.json"
                    metrics_path = f"{results_prefix}/fastpath_metrics.json"
                    chart_path = f"{results_prefix}/fastpath_chart_data.json"
                    summary_path = f"{results_prefix}/summary.json"
                    command_path = f"{results_prefix}/command.json"
                    strategy_path = f"{results_prefix}/strategy.json"

                    try:
                        table_blob = bucket.blob(table_path)
                        metrics_blob = bucket.blob(metrics_path)
                        chart_blob = bucket.blob(chart_path)
                        summary_blob = bucket.blob(summary_path)
                        command_blob = bucket.blob(command_path)
                        strategy_blob = bucket.blob(strategy_path)

                        table_data = json.dumps({"rows": table_rows}, ensure_ascii=False).encode("utf-8")
                        metrics_data = json.dumps(metrics, ensure_ascii=False).encode("utf-8")
                        chart_data_json = json.dumps(chart_data, ensure_ascii=False).encode("utf-8")
                        summary_data = json.dumps({"text": summary_text}, ensure_ascii=False).encode("utf-8")
                        command_obj = {
                            "intent": intent,
                            "params": resolved_params,
                            "confidence": confidence,
                            "toolkitVersion": TOOLKIT_VERSION,
                        }
                        command_data = json.dumps(command_obj, ensure_ascii=False).encode("utf-8")
                        strategy_obj = {
                            "strategy": "fastpath",
                            "version": TOOLKIT_VERSION,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "messageId": message_id,
                            "question": question,
                            "command": command_obj,
                        }
                        strategy_data = json.dumps(strategy_obj, ensure_ascii=False).encode("utf-8")

                        with ThreadPoolExecutor(max_workers=6) as executor:
                            futures = [
                                executor.submit(table_blob.upload_from_string, table_data, content_type="application/json"),
                                executor.submit(metrics_blob.upload_from_string, metrics_data, content_type="application/json"),
                                executor.submit(chart_blob.upload_from_string, chart_data_json, content_type="application/json"),
                                executor.submit(summary_blob.upload_from_string, summary_data, content_type="application/json"),
                                executor.submit(command_blob.upload_from_string, command_data, content_type="application/json"),
                                executor.submit(strategy_blob.upload_from_string, strategy_data, content_type="application/json"),
                            ]
                            for f in futures:
                                f.result()
                        table_url = _sign_gs_uri(f"gs://{FILES_BUCKET}/{table_path}")
                        metrics_url = _sign_gs_uri(f"gs://{FILES_BUCKET}/{metrics_path}")
                        chart_url = _sign_gs_uri(f"gs://{FILES_BUCKET}/{chart_path}")
                        summary_url = _sign_gs_uri(f"gs://{FILES_BUCKET}/{summary_path}")
                    except Exception as e:
                        yield _sse_format({"type": "error", "data": {"code": "PERSIST_FAILED", "message": str(e)}})
                        return

                    yield _sse_format({
                        "type": "done",
                        "data": {
                            "messageId": message_id,
                            "summary": summary_text,
                            "tableSample": table_rows,
                            "chartData": chart_data,
                            "metrics": metrics,
                            "strategy": "fastpath",
                            "uris": {
                                "table": table_url,
                                "metrics": metrics_url,
                                "chartData": chart_url,
                                "summary": summary_url
                            }
                        }
                    })
                    return
                except Exception:
                    try:
                        yield _sse_format({"type": "fastpath_error", "data": {"message": "A quick path failed; trying a more flexible approach."}})
                    except Exception:
                        pass
                    try:
                        logging.info(json.dumps({
                            "event": "router_decision",
                            "strategy": "fallback",
                            "reason": "fastpath_error",
                            "intent": intent,
                            "confidence": confidence,
                        }))
                    except Exception:
                        pass

    # --- Main Generation and Validation Loop ---
    yield _sse_format({"type": "generating_code"})
    code, is_valid, validation_errors, warnings = "", False, ["Code generation failed."], []
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            # Time-bounded code generation with keepalive pings
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(gemini_client.generate_code_and_summary, question, schema_snippet, sample_rows)
                remaining = CODEGEN_TIMEOUT_SECONDS
                while True:
                    try:
                        raw_code, llm_response_text = fut.result(timeout=min(remaining, 2))
                        break
                    except FuturesTimeout:
                        # Keep the connection alive for the UI
                        try:
                            yield _sse_format({"type": "still_working"})
                        except Exception:
                            pass
                        remaining -= 2
                        if remaining <= 0:
                            raise

            if not raw_code:
                # If code extraction fails, use the raw response for the repair prompt
                validation_errors = [f"LLM did not return a valid code block. Response: {llm_response_text[:200]}"]
                question = f"The previous attempt failed. Please fix it. The error was: {validation_errors[0]}. Original question: {question}"
                continue # Retry

            # Validate the generated code
            is_valid, validation_errors, warnings = sandbox_runner.validate_code(raw_code)
            
            if is_valid:
                code = raw_code
                break # Success
            else:
                # If validation fails, use the errors for the repair prompt
                question = f"The previous code failed validation. Please fix it. Errors: {'; '.join(validation_errors)}. Original question: {question}"

        except FuturesTimeout:
            # Application-level timeout for code generation
            yield _sse_format({
                "type": "error",
                "data": {
                    "code": "CODEGEN_TIMEOUT",
                    "message": f"Analysis step took longer than {CODEGEN_TIMEOUT_SECONDS}s. Please rephrase or try again.",
                },
            })
            return
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
                "warnings": (warnings or []),
                "source": "fallback_execution",
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
                    "data": {"language": "python", "text": code, "warnings": (warnings or []), "source": "fallback_execution"}
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
    table_path = f"{results_prefix}/fallback_table.json"
    metrics_path = f"{results_prefix}/fallback_metrics.json"
    chart_path = f"{results_prefix}/fallback_chart_data.json"
    summary_path = f"{results_prefix}/summary.json"
    strategy_path = f"{results_prefix}/strategy.json"
    exec_code_path = f"{results_prefix}/fallback_exec_code.py"
    
    try:
        table_blob = bucket.blob(table_path)
        metrics_blob = bucket.blob(metrics_path)
        chart_blob = bucket.blob(chart_path)
        summary_blob = bucket.blob(summary_path)
        strategy_blob = bucket.blob(strategy_path)
        exec_code_blob = bucket.blob(exec_code_path)
        
        table_data = json.dumps({"rows": table}, ensure_ascii=False).encode("utf-8")
        metrics_data = json.dumps(metrics, ensure_ascii=False).encode("utf-8")
        chart_data_json = json.dumps(chart_data, ensure_ascii=False).encode("utf-8")
        summary_data = json.dumps({"text": summary}, ensure_ascii=False).encode("utf-8")
        
        # Upload in parallel (do not expose exec code URL)
        strategy_obj = {
            "strategy": "fallback",
            "version": TOOLKIT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "messageId": message_id,
            "question": question,
        }
        strategy_data = json.dumps(strategy_obj, ensure_ascii=False).encode("utf-8")

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [
                executor.submit(table_blob.upload_from_string, table_data, content_type="application/json"),
                executor.submit(metrics_blob.upload_from_string, metrics_data, content_type="application/json"),
                executor.submit(chart_blob.upload_from_string, chart_data_json, content_type="application/json"), 
                executor.submit(summary_blob.upload_from_string, summary_data, content_type="application/json"),
                executor.submit(strategy_blob.upload_from_string, strategy_data, content_type="application/json"),
                executor.submit(exec_code_blob.upload_from_string, code.encode("utf-8"), content_type="text/plain"),
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
            "strategy": "fallback",
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