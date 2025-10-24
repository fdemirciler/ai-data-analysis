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
import config
import embedding_router
from google.api_core import exceptions as gax_exceptions  # type: ignore
import logging
from functools import lru_cache
import re

# Configuration (centralized)
PROJECT_ID = config.PROJECT_ID
FILES_BUCKET = config.FILES_BUCKET
PING_INTERVAL_SECONDS = config.SSE_PING_INTERVAL_SECONDS
HARD_TIMEOUT_SECONDS = config.CHAT_HARD_TIMEOUT_SECONDS
REPAIR_TIMEOUT_SECONDS = config.CHAT_REPAIR_TIMEOUT_SECONDS
ORCH_IPC_MODE = config.ORCH_IPC_MODE
RUNTIME_SERVICE_ACCOUNT = config.RUNTIME_SERVICE_ACCOUNT

FASTPATH_ENABLED = config.FASTPATH_ENABLED
FALLBACK_ENABLED = config.FALLBACK_ENABLED
CODE_RECONSTRUCT_ENABLED = config.CODE_RECONSTRUCT_ENABLED
MIN_FASTPATH_CONFIDENCE = config.MIN_FASTPATH_CONFIDENCE
CLASSIFIER_TIMEOUT_SECONDS = config.CLASSIFIER_TIMEOUT_SECONDS
MAX_FASTPATH_ROWS = config.MAX_FASTPATH_ROWS
FORCE_FALLBACK_MIN_ROWS = config.FORCE_FALLBACK_MIN_ROWS
MAX_CHART_POINTS = config.MAX_CHART_POINTS
TOOLKIT_VERSION = config.TOOLKIT_VERSION
MIRROR_COMMAND_TO_FIRESTORE = config.MIRROR_COMMAND_TO_FIRESTORE
CODEGEN_TIMEOUT_SECONDS = config.CODEGEN_TIMEOUT_SECONDS

ALLOWED_ORIGINS = config.ALLOWED_ORIGINS

# Firebase Admin SDK Initialization
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app()


def _origin_allowed(origin: str | None) -> bool:
    return origin in ALLOWED_ORIGINS if origin else False

# Validate configuration at startup (logs warnings for suspicious values)
try:
    config.validate_config(logger=logging)
except Exception:
    pass


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
    columns_schema = payload_obj.get("columns", {}) or {}

    # --- Router helpers: DESCRIBE lexicon and multi-metric detection ---
    def _is_describe_like(q: str) -> bool:
        if not isinstance(q, str) or not q:
            return False
        ql = q.lower()
        # Expanded lexicon per decision
        lex = ["describe", "summary", "summarize", "overview", "stats", "schema", "fields"]
        has_keyword = any(re.search(rf"\b{re.escape(tok)}\b", ql) for tok in lex)
        has_grouping = bool(re.search(r"\b(by|per)\b", ql))
        return has_keyword and not has_grouping

    def _is_multi_metric_request(q: str, col_names: list[str], cols_schema: dict) -> bool:
        if not isinstance(q, str) or not q:
            return False
        ql = q.lower()
        # Heuristic: mentions average/mean and has conjunctions and grouping cue
        pattern_avg = bool(re.search(r"\b(avg|average|mean)\b", ql))
        pattern_multi = bool(re.search(r"\b(and)\b|,", ql))
        pattern_group = bool(re.search(r"\b(by|per)\b", ql))

        # Column resolution: count unique resolved columns referenced in question
        tokens = re.findall(r"[a-zA-Z0-9_]+", ql)
        resolved: set[str] = set()
        for t in tokens:
            col = aliases.resolve_column(t, col_names)
            if col:
                # Optionally check numeric-ish types if provided in schema
                meta = (cols_schema or {}).get(col, {})
                dtype = str(meta.get("dtype") or meta.get("type") or "").lower()
                if dtype:
                    if any(k in dtype for k in ["int", "float", "number", "numeric", "double", "decimal"]):
                        resolved.add(col)
                    else:
                        # If dtype present but non-numeric, skip
                        continue
                else:
                    # If no dtype info, still count the resolved column
                    resolved.add(col)

        return (pattern_avg and pattern_multi and pattern_group) or (len(resolved) >= 2 and pattern_group)

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

                style = config.PRESENTATIONAL_CODE_STYLE
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
        if config.EMBED_ROUTER_ENABLED:
            intent_guess, embed_score = None, 0.0
            try:
                intent_guess, embed_score = embedding_router.semantic_route(
                    question, model=config.EMBED_MODEL, timeout_s=config.EMBED_TIMEOUT_SECONDS
                )
            except Exception:
                intent_guess, embed_score = None, 0.0

            if intent_guess is not None:
                try:
                    threshold = embedding_router.get_embed_threshold(intent_guess)
                except Exception:
                    threshold = float(config.EMBED_THRESHOLD_DEFAULT)

                passes_guards = True
                if intent_guess == "run_describe" and (not _is_describe_like(question)):
                    passes_guards = False
                if intent_guess == "run_aggregation" and _is_multi_metric_request(question, column_names, columns_schema):
                    passes_guards = False

                if embed_score >= threshold and passes_guards:
                    restricted_spec = [t for t in (analysis_toolkit.TOOLS_SPEC or []) if t.get("name") == intent_guess]
                    if restricted_spec:
                        try:
                            with ThreadPoolExecutor(max_workers=1) as ex:
                                fut = ex.submit(
                                    gemini_client.classify_intent,
                                    question,
                                    schema_snippet,
                                    sample_rows,
                                    restricted_spec,
                                    hinting,
                                )
                                try:
                                    classification = fut.result(timeout=3)
                                except FuturesTimeout:
                                    classification = None
                        except Exception:
                            classification = None
                try:
                    logging.info(json.dumps({
                        "event": "embed_router",
                        "intent_guess": intent_guess,
                        "score": embed_score,
                        "threshold": threshold if intent_guess is not None else None,
                        "accepted": bool(classification),
                    }))
                except Exception:
                    pass

        if classification is None:
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
            # legacy
            "run_aggregation": "AGGREGATE",
            "run_variance": "VARIANCE",
            "run_filter_and_sort": "FILTER_SORT",
            "run_describe": "DESCRIBE",
            # new tranche-1
            "filter_rows": "FILTER",
            "sort_rows": "SORT",
            "value_counts": "VALUE_COUNTS",
            "top_n_per_group": "TOP_N_PER_GROUP",
            "pivot_table": "PIVOT",
            "percentile": "PERCENTILE",
            "outliers": "OUTLIERS",
            # simple global aggregate
            "sum_column": "SUM_COLUMN",
        }
        intent = name_map.get(str(raw_intent), str(raw_intent).upper())

        # Params are expected in snake_case as defined in TOOLS_SPEC
        params = dict(raw_params)

        # Case-insensitive column resolution helper
        def _smart_resolve_column(name: str, cols: list[str]) -> str | None:
            """Resolve column with case-insensitive fallback before fuzzy matching."""
            if not name:
                return None
            
            # 1. Exact match
            if name in cols:
                return name
            
            # 2. Case-insensitive match
            name_lower = name.lower()
            for c in cols:
                if c.lower() == name_lower:
                    return c
            
            # 3. Alias + fuzzy (existing logic)
            return aliases.resolve_column(name, cols)

        # Parameter validation and resolution
        def _validate_and_resolve(i: str, p: dict) -> tuple[bool, dict]:
            resolved = dict(p)
            try:
                if i == "AGGREGATE":
                    resolved["dimension"] = _smart_resolve_column(p.get("dimension"), column_names) or p.get("dimension")
                    resolved["metric"] = _smart_resolve_column(p.get("metric"), column_names) or p.get("metric")
                    return bool(resolved.get("dimension") and resolved.get("metric") and p.get("func")), resolved
                if i == "VARIANCE":
                    resolved["dimension"] = _smart_resolve_column(p.get("dimension"), column_names) or p.get("dimension")
                    resolved["period_a"] = _smart_resolve_column(p.get("period_a"), column_names) or p.get("period_a")
                    resolved["period_b"] = _smart_resolve_column(p.get("period_b"), column_names) or p.get("period_b")
                    return bool(resolved.get("dimension") and resolved.get("period_a") and resolved.get("period_b")), resolved
                if i == "FILTER_SORT":
                    resolved["sort_col"] = _smart_resolve_column(p.get("sort_col"), column_names) or p.get("sort_col")
                    if p.get("filter_col"):
                        resolved["filter_col"] = _smart_resolve_column(p.get("filter_col"), column_names) or p.get("filter_col")
                    return bool(resolved.get("sort_col")), resolved
                if i == "DESCRIBE":
                    return True, resolved
                if i == "FILTER":
                    flist = []
                    for f in (p.get("filters") or []):
                        col = _smart_resolve_column(f.get("column"), column_names) or f.get("column")
                        flist.append({
                            "column": col,
                            "operator": f.get("operator"),
                            "value": f.get("value"),
                        })
                    resolved["filters"] = flist
                    return bool(flist), resolved
                if i == "SORT":
                    resolved["sort_by_column"] = _smart_resolve_column(p.get("sort_by_column"), column_names) or p.get("sort_by_column")
                    return bool(resolved.get("sort_by_column")), resolved
                if i == "VALUE_COUNTS":
                    resolved["column"] = _smart_resolve_column(p.get("column"), column_names) or p.get("column")
                    return bool(resolved.get("column")), resolved
                if i == "TOP_N_PER_GROUP":
                    resolved["group_by_column"] = _smart_resolve_column(p.get("group_by_column"), column_names) or p.get("group_by_column")
                    resolved["metric_column"] = _smart_resolve_column(p.get("metric_column"), column_names) or p.get("metric_column")
                    return bool(resolved.get("group_by_column") and resolved.get("metric_column")), resolved
                if i == "PIVOT":
                    resolved["index"] = _smart_resolve_column(p.get("index"), column_names) or p.get("index")
                    resolved["columns"] = _smart_resolve_column(p.get("columns"), column_names) or p.get("columns")
                    resolved["values"] = _smart_resolve_column(p.get("values"), column_names) or p.get("values")
                    return bool(resolved.get("index") and resolved.get("columns") and resolved.get("values")), resolved
                if i == "PERCENTILE":
                    resolved["column"] = _smart_resolve_column(p.get("column"), column_names) or p.get("column")
                    # p may be string or number; defer casting to toolkit
                    return bool(resolved.get("column") and ("p" in p)), resolved
                if i == "OUTLIERS":
                    resolved["column"] = _smart_resolve_column(p.get("column"), column_names) or p.get("column")
                    return bool(resolved.get("column")), resolved
                if i == "SUM_COLUMN":
                    resolved["column"] = _smart_resolve_column(p.get("column"), column_names) or p.get("column")
                    return bool(resolved.get("column")), resolved
            except Exception:
                return False, resolved
            return False, resolved

        params_ok, resolved_params = _validate_and_resolve(intent, params)

        # Soft-accept logic (stricter): require params_ok for ANY fastpath, keep tighter soft threshold
        soft_threshold = max(0.0, MIN_FASTPATH_CONFIDENCE - 0.10)
        is_fastpath_candidate = False

        if intent == "DESCRIBE":
            # DESCRIBE: only when clearly a describe-like request, never if grouping cues present
            is_fastpath_candidate = (
                params_ok
                and _is_describe_like(question)
                and (confidence >= MIN_FASTPATH_CONFIDENCE or confidence >= soft_threshold)
            )
            if not is_fastpath_candidate:
                try:
                    logging.info(json.dumps({
                        "event": "router_decision",
                        "strategy": "fallback",
                        "intent": intent,
                        "reason": "describe_not_clear"
                    }))
                except Exception:
                    pass
        elif intent in {"AGGREGATE", "VARIANCE", "FILTER_SORT"}:
            # Capability guard for AGGREGATE: multi-metric grouped tables require fallback
            if intent == "AGGREGATE" and _is_multi_metric_request(question, column_names, columns_schema):
                is_fastpath_candidate = False
                try:
                    logging.info(json.dumps({
                        "event": "router_decision",
                        "strategy": "fallback",
                        "intent": intent,
                        "reason": "multi_metric_guard"
                    }))
                except Exception:
                    pass
            else:
                is_fastpath_candidate = params_ok and (
                    confidence >= MIN_FASTPATH_CONFIDENCE or confidence >= soft_threshold
                )
        elif intent in {"FILTER", "SORT", "VALUE_COUNTS", "TOP_N_PER_GROUP", "PIVOT", "PERCENTILE", "OUTLIERS", "SUM_COLUMN"}:
            # For new deterministic intents, accept with same policy: params_ok + threshold
            is_fastpath_candidate = params_ok and (
                confidence >= MIN_FASTPATH_CONFIDENCE or confidence >= soft_threshold
            )

        # Optional SSE for debugging (no data rows logged)
        if config.LOG_CLASSIFIER_RESPONSE:
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
                    # Determine needed columns using a central helper
                    def _col_prune_disabled(intent_name: str) -> bool:
                        return config.fastpath_disable_column_prune(intent_name)

                    def compute_needed_cols(intent_name: str, rp: dict) -> list[str] | None:
                        if _col_prune_disabled(intent_name):
                            return None
                        if intent_name == "AGGREGATE":
                            return [c for c in [rp.get("dimension"), rp.get("metric")] if c]
                        if intent_name == "VARIANCE":
                            return [c for c in [rp.get("dimension"), rp.get("period_a"), rp.get("period_b")] if c]
                        if intent_name == "FILTER_SORT":
                            return [c for c in [rp.get("sort_col"), rp.get("filter_col")] if c]
                        if intent_name == "FILTER":
                            cols = []
                            for f in (rp.get("filters") or []):
                                if f.get("column"):
                                    cols.append(f["column"])
                            return list(dict.fromkeys(cols)) or None
                        if intent_name == "SORT":
                            return [c for c in [rp.get("sort_by_column")] if c]
                        if intent_name == "VALUE_COUNTS":
                            return [c for c in [rp.get("column")] if c]
                        if intent_name == "TOP_N_PER_GROUP":
                            return [c for c in [rp.get("group_by_column"), rp.get("metric_column")] if c]
                        if intent_name == "PIVOT":
                            return [c for c in [rp.get("index"), rp.get("columns"), rp.get("values")] if c]
                        if intent_name == "PERCENTILE":
                            return [c for c in [rp.get("column")] if c]
                        if intent_name == "OUTLIERS":
                            return [c for c in [rp.get("column")] if c]
                        if intent_name == "SUM_COLUMN":
                            return [c for c in [rp.get("column")] if c]
                        return None

                    needed_cols = compute_needed_cols(intent, resolved_params)

                    if needed_cols:
                        df = pd.read_parquet(io.BytesIO(parquet_bytes), columns=needed_cols)
                    else:
                        df = pd.read_parquet(io.BytesIO(parquet_bytes))
                    if MAX_FASTPATH_ROWS > 0 and len(df) > MAX_FASTPATH_ROWS:
                        df = df.head(MAX_FASTPATH_ROWS)

                    # Execute
                    if intent == "AGGREGATE":
                        dim = resolved_params.get("dimension")
                        met = resolved_params.get("metric")
                        res_df = analysis_toolkit.run_aggregation(df, dim, met, resolved_params.get("func", params.get("func", "sum")))
                    elif intent == "VARIANCE":
                        dim = resolved_params.get("dimension")
                        a = resolved_params.get("period_a")
                        b = resolved_params.get("period_b")
                        res_df = analysis_toolkit.run_variance(df, dim, a, b)
                    elif intent == "FILTER_SORT":
                        sort_col = resolved_params.get("sort_col")
                        fcol = resolved_params.get("filter_col")
                        res_df = analysis_toolkit.run_filter_and_sort(
                            df,
                            sort_col=sort_col,
                            ascending=bool(resolved_params.get("ascending", params.get("ascending", False))),
                            limit=int((resolved_params.get("limit") or params.get("limit") or 50)),
                            filter_col=fcol,
                            filter_val=resolved_params.get("filter_val", params.get("filter_val")),
                        )
                    elif intent == "FILTER":
                        res_df = analysis_toolkit.filter_rows(df, filters=resolved_params.get("filters") or [])
                    elif intent == "SORT":
                        res_df = analysis_toolkit.sort_rows(
                            df,
                            sort_by_column=resolved_params.get("sort_by_column"),
                            ascending=bool(resolved_params.get("ascending", False)),
                            limit=int(resolved_params.get("limit") or 0),
                        )
                    elif intent == "VALUE_COUNTS":
                        res_df = analysis_toolkit.value_counts(
                            df,
                            column=resolved_params.get("column"),
                            top=int(resolved_params.get("top") or 100),
                            include_pct=bool(resolved_params.get("include_pct", True)),
                        )
                    elif intent == "TOP_N_PER_GROUP":
                        res_df = analysis_toolkit.top_n_per_group(
                            df,
                            group_by_column=resolved_params.get("group_by_column"),
                            metric_column=resolved_params.get("metric_column"),
                            n=int(resolved_params.get("n") or 5),
                            ascending=bool(resolved_params.get("ascending", False)),
                        )
                    elif intent == "PIVOT":
                        res_df = analysis_toolkit.pivot_table(
                            df,
                            index=resolved_params.get("index"),
                            columns=resolved_params.get("columns"),
                            values=resolved_params.get("values"),
                            aggfunc=str(resolved_params.get("aggfunc") or "sum"),
                        )
                    elif intent == "PERCENTILE":
                        res_df = analysis_toolkit.percentile(
                            df,
                            column=resolved_params.get("column"),
                            p=resolved_params.get("p"),
                        )
                    elif intent == "OUTLIERS":
                        res_df = analysis_toolkit.outliers(
                            df,
                            column=resolved_params.get("column"),
                            method=str(resolved_params.get("method") or "iqr"),
                            k=resolved_params.get("k", 1.5),
                        )
                    elif intent == "SUM_COLUMN":
                        res_df = analysis_toolkit.sum_column(
                            df,
                            column=resolved_params.get("column"),
                        )
                    else:
                        res_df = analysis_toolkit.run_describe(df)

                    # Summarization with timeout for resilience
                    summary_obj = {}
                    try:
                        with ThreadPoolExecutor(max_workers=1) as ex:
                            fut = ex.submit(gemini_client.format_final_response, question, res_df)
                            summary_obj = fut.result(timeout=15)
                    except Exception as e:
                        try:
                            logging.warning(f"Summarization call failed or timed out: {e}")
                        except Exception:
                            pass
                        summary_obj = {"summary": "The analysis is complete. Please review the data below."}
                    summary_text = summary_obj.get("summary") or ""
                    # Optional title generation (non-blocking)
                    title_text = None
                    try:
                        title_text = gemini_client.generate_title(question, summary_text)
                    except Exception as e:
                        try:
                            logging.info(json.dumps({"event": "title_generate_error", "detail": str(e)[:200]}))
                        except Exception:
                            pass
                    table_rows = res_df.head(200).to_dict(orient="records")
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

                    _data = {
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
                            "summary": summary_url,
                        },
                    }
                    if isinstance(title_text, str) and title_text.strip():
                        _data["title"] = title_text.strip()
                    yield _sse_format({"type": "done", "data": _data})
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
    
    # Optional title generation (non-blocking)
    title_text = None
    try:
        title_text = gemini_client.generate_title(question, summary)
    except Exception as e:
        try:
            logging.info(json.dumps({"event": "title_generate_error", "detail": str(e)[:200]}))
        except Exception:
            pass

    # Final 'done' event with URLs
    _data = {
        "messageId": message_id,
        "summary": summary,
        "tableSample": table[:200],  # Send up to 200 rows to frontend
        "chartData": chart_data,
        "metrics": metrics,
        "strategy": "fallback",
        "uris": {
            "table": table_url,
            "metrics": metrics_url,
            "chartData": chart_url,
            "summary": summary_url,
        },
    }
    if isinstance(title_text, str) and title_text.strip():
        _data["title"] = title_text.strip()
    yield _sse_format({"type": "done", "data": _data})


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
