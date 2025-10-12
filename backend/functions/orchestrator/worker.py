#!/usr/bin/env python3
"""
Worker process to safely execute LLM-generated analysis code in a sandboxed environment.

This script is launched as a subprocess by the orchestrator. It receives JSON via stdin:
{
  "code": "<python source>",
  "parquet_b64": "<base64 bytes>" | optional,
  "arrow_ipc_b64": "<base64 bytes>" | optional,
  "parquet_path": "/tmp/cleaned.parquet" | optional,
  "ctx": { ... }
}

Steps:
1. Validate code with sandbox_runner.
2. Load the dataset into a DataFrame.
3. Execute the validated run(df, ctx) safely.
4. Sanitize and normalize the result for JSON output.

It always prints a JSON payload to stdout and exits with 0 unless the payload is malformed.
"""
from __future__ import annotations

import io
import json
import base64
import sys
import signal
import traceback
import os
from typing import Any

import pandas as pd
import numpy as np
import pyarrow as pa  # type: ignore

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns

# Try to import sandbox validator (preferred)
try:
    from sandbox_runner import structured_validate, ALLOWED_IMPORTS as SANDBOX_ALLOWED_IMPORTS
except Exception:
    SANDBOX_ALLOWED_IMPORTS = {
        "pandas", "numpy", "matplotlib", "seaborn",
        "math", "statistics", "json", "io", "itertools", "functools",
        "collections", "re", "datetime", "base64"
    }
    structured_validate = None  # fallback


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
import config

ALLOWED_IMPORTS = set(SANDBOX_ALLOWED_IMPORTS)
CODE_TIMEOUT = int(config.CODE_TIMEOUT)
MAX_MEMORY_BYTES = int(config.CODE_MAX_MEMORY_BYTES)  # 512MB default
try:
    import resource
except Exception:
    resource = None


# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------
def sanitize_for_json(obj: Any) -> Any:
    """Recursively replaces NaN/Inf with None for Firestore/JSON compatibility."""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    return obj


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = (name.split(".") or [name])[0]
    if root not in ALLOWED_IMPORTS:
        raise ImportError(f"Import not allowed: {name}")
    return _orig_import(name, globals, locals, fromlist, level)


def _prepare_globals() -> dict:
    """Prepare restricted globals for execution."""
    import builtins as _builtins
    safe_builtins = {
        b: getattr(_builtins, b)
        for b in [
            "abs", "all", "any", "bool", "dict", "enumerate", "filter",
            "float", "int", "len", "list", "map", "max", "min", "pow",
            "range", "round", "set", "slice", "sorted", "str", "sum",
            "zip", "print", "isinstance", "getattr", "hasattr", "type",
        ]
        if hasattr(_builtins, b)
    }
    safe_builtins["__import__"] = _safe_import
    return {"__builtins__": safe_builtins, "pd": pd, "np": np, "plt": plt, "sns": sns, "RESULT": None}


def _set_resource_limits():
    """Apply memory and CPU limits (POSIX only)."""
    if resource is None:
        return
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
    except Exception:
        pass
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (CODE_TIMEOUT + 5, CODE_TIMEOUT + 5))
    except Exception:
        pass


class _TimeoutException(Exception):
    pass


def _timeout_handler(signum, frame):
    raise _TimeoutException("User code timed out")


def _load_dataframe(payload: dict) -> pd.DataFrame:
    """Load df from base64 Parquet/Arrow or path."""
    if payload.get("arrow_ipc_b64"):
        ipc_bytes = base64.b64decode(payload["arrow_ipc_b64"])
        with pa.ipc.open_stream(io.BytesIO(ipc_bytes)) as reader:
            table = reader.read_all()
        return table.to_pandas()
    if payload.get("parquet_b64"):
        data = base64.b64decode(payload["parquet_b64"])
        return pd.read_parquet(io.BytesIO(data))
    if payload.get("parquet_path"):
        return pd.read_parquet(payload["parquet_path"])
    raise ValueError("Missing data payload: no parquet_b64, arrow_ipc_b64, or parquet_path provided")


def _fallback_result(df: pd.DataFrame, ctx: dict) -> dict:
    """Fallback minimal result when code fails."""
    row_limit = int((ctx or {}).get("row_limit", 200))
    return {
        "table": df.head(row_limit).to_dict(orient="records"),
        "metrics": {"rows": len(df), "columns": len(df.columns)},
        "chartData": {},
        "message": "Fallback result generated due to code execution failure."
    }


# --------------------------------------------------------------------------
# Main Execution
# --------------------------------------------------------------------------
def main() -> int:
    global _orig_import
    import builtins as _builtins
    _orig_import = _builtins.__import__

    # Step 1: Read payload
    try:
        payload = json.load(sys.stdin)
        code = payload.get("code", "")
        ctx = payload.get("ctx", {}) or {}
        if not code:
            raise ValueError("Missing 'code' field in payload")
    except Exception as e:
        sys.stderr.write(f"Invalid input payload: {e}\n")
        return 1

    # Step 2: Validate code via sandbox_runner
    try:
        if structured_validate:
            validation = structured_validate(code)
            if not validation.get("ok", False):
                output = {
                    "table": [],
                    "metrics": {},
                    "chartData": {},
                    "error": "Validation failed",
                    "validation": validation,
                }
                print(json.dumps(output, ensure_ascii=False))
                return 0
    except Exception as e:
        output = {
            "table": [],
            "metrics": {},
            "chartData": {},
            "error": f"Validator error: {e}",
        }
        print(json.dumps(output, ensure_ascii=False))
        return 0

    # Step 3: Load DataFrame
    try:
        df = _load_dataframe(payload)
    except Exception as e:
        output = {"table": [], "metrics": {}, "chartData": {}, "error": f"Failed to load data: {e}"}
        print(json.dumps(output, ensure_ascii=False))
        return 0

    # Step 4: Execute code safely
    globs = _prepare_globals()
    locs: dict = {}

    _set_resource_limits()
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(CODE_TIMEOUT)

    try:
        compiled = compile(code, filename="<user_code>", mode="exec")
        exec(compiled, globs, locs)

        run_func = locs.get("run") or globs.get("run")
        if not callable(run_func):
            raise RuntimeError("Missing required function: def run(df, ctx):")

        result = run_func(df, ctx)
        if result is None:
            result = globs.get("RESULT")

        # Normalize
        if isinstance(result, pd.DataFrame):
            result = {"table": result.to_dict(orient="records"), "metrics": {}, "chartData": {}}
        elif isinstance(result, list):
            result = {"table": result, "metrics": {}, "chartData": {}}
        elif not isinstance(result, dict):
            result = _fallback_result(df, ctx)

        # Map plural keys to canonical ones when needed
        if isinstance(result, dict):
            # tables -> table (choose first reasonable table)
            if "table" not in result and "tables" in result:
                tables = result.get("tables")
                table_rows = None
                try:
                    if isinstance(tables, list) and len(tables) > 0:
                        first = tables[0]
                        if isinstance(first, pd.DataFrame):
                            table_rows = first.to_dict(orient="records")
                        elif isinstance(first, list):
                            table_rows = first
                        elif isinstance(first, dict):
                            table_rows = [first]
                    elif isinstance(tables, dict) and len(tables) > 0:
                        for v in tables.values():
                            if isinstance(v, pd.DataFrame):
                                table_rows = v.to_dict(orient="records")
                                break
                            elif isinstance(v, list):
                                table_rows = v
                                break
                            elif isinstance(v, dict):
                                table_rows = [v]
                                break
                except Exception:
                    table_rows = None
                if table_rows is not None:
                    result["table"] = table_rows

            # charts -> chartData (choose first chart-like dict)
            if "chartData" not in result and "charts" in result:
                charts = result.get("charts")
                chosen = None
                if isinstance(charts, dict):
                    chosen = charts
                elif isinstance(charts, list) and len(charts) > 0:
                    chosen = charts[0]
                if isinstance(chosen, dict):
                    result["chartData"] = chosen

        # Ensure required keys
        result.setdefault("table", df.head(int(ctx.get("row_limit", 200))).to_dict(orient="records"))
        result.setdefault("metrics", {"rows": len(df), "columns": len(df.columns)})
        result.setdefault("chartData", {})

        sanitized = sanitize_for_json(result)
        print(json.dumps(sanitized, ensure_ascii=False))
        return 0

    except _TimeoutException:
        output = {"table": [], "metrics": {}, "chartData": {}, "error": f"Execution timed out after {CODE_TIMEOUT}s."}
        print(json.dumps(output, ensure_ascii=False))
        return 0

    except Exception as e:
        tb = traceback.format_exc(limit=8)
        output = {
            "table": [],
            "metrics": {},
            "chartData": {},
            "error": f"Runtime error: {e}",
            "traceback": tb,
        }
        print(json.dumps(output, ensure_ascii=False))
        return 0

    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


if __name__ == "__main__":
    raise SystemExit(main())
