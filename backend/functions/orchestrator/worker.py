"""
Worker process to execute LLM-generated analysis code safely.

Usage: launched by the parent orchestrator via subprocess with JSON on stdin:
{
  "code": "<python source>",
  "parquet_path": "/tmp/cleaned.parquet",
  "ctx": { ... }
}

It will:
- Load df from parquet using pandas/pyarrow
- Execute validated code with restricted builtins and guarded __import__
- Invoke run(df, ctx) and return RESULT as JSON on stdout

Exit codes:
- 0: success, stdout contains RESULT JSON
- 1: validation or runtime error, stderr contains a short message
"""
from __future__ import annotations

import io
import json
import base64
import sys
import types

import pandas as pd  # noqa: F401  (provided as pd)
import numpy as np  # noqa: F401  (provided as np)
import pyarrow as pa  # type: ignore

ALLOWED_IMPORTS = {"pandas", "numpy", "math", "json"}


def sanitize_for_firestore(obj):
    """Recursively traverses a dict/list to replace NaN, Inf, -Inf with None."""
    if isinstance(obj, dict):
        return {k: sanitize_for_firestore(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_firestore(item) for item in obj]
    elif isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
    return obj


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: D401
    """Restricted import: only allow ALLOWED_IMPORTS root modules."""
    root = name.split(".")[0]
    if root not in ALLOWED_IMPORTS:
        raise ImportError(f"Import not allowed: {name}")
    return _orig_import(name, globals, locals, fromlist, level)


def _prepare_globals():
    import builtins as _builtins

    safe_builtins = {}
    allowlist = {
        "abs", "all", "any", "bool", "dict", "enumerate", "filter",
        "float", "int", "len", "list", "map", "max", "min", "pow",
        "range", "round", "set", "slice", "sorted", "str", "sum",
        "zip", "print",  # benign
    }
    for k in allowlist:
        if hasattr(_builtins, k):
            safe_builtins[k] = getattr(_builtins, k)

    # Guard __import__
    safe_builtins["__import__"] = _safe_import

    globs = {
        "__builtins__": safe_builtins,
        "pd": pd,
        "np": np,
        "RESULT": None,
    }
    return globs


def _build_fallback_from_df(df: pd.DataFrame, ctx: dict) -> dict:
    """Create a minimal RESULT dict from a DataFrame sample."""
    try:
        row_limit = int((ctx or {}).get("row_limit", 200))
    except Exception:
        row_limit = 200
    table = df.head(row_limit).to_dict(orient="records")
    metrics = {"rows": int(len(df)), "columns": int(len(df.columns))}
    # Decide whether a fallback chart is allowed and explicitly requested
    try:
        q = str((ctx or {}).get("question") or "").lower()
    except Exception:
        q = ""
    wants_chart = any(tok in q for tok in ("chart", "plot", "graph", "visualization"))
    if not wants_chart:
        # Respect rule: no chart unless explicitly asked
        chart = {}
    else:
        chart = {"kind": "bar", "labels": [], "series": [{"label": "Count", "data": []}]}
        # Prefer a categorical distribution; else a numeric preview
        try:
            obj_cols = [c for c in df.columns if df[c].dtype == "object"]
            if obj_cols:
                vc = df[obj_cols[0]].astype("string").value_counts().head(5)
                chart["labels"] = [str(x) for x in vc.index.tolist()]
                chart["series"][0]["data"] = [int(x) for x in vc.values.tolist()]
            else:
                num_cols = df.select_dtypes(include=["number"]).columns.tolist()
                if num_cols:
                    s = df[num_cols[0]].dropna().head(5)
                    chart["labels"] = [str(i) for i in range(len(s))]
                    chart["series"][0]["data"] = [float(x) for x in s.tolist()]
        except Exception:
            # Keep minimal chart structure on failure
            pass
    return {"table": table, "metrics": metrics, "chartData": chart}


def main() -> int:
    global _orig_import  # noqa: PLW0603
    import builtins as _builtins

    _orig_import = _builtins.__import__

    try:
        payload = json.load(sys.stdin)
        code = payload.get("code", "")
        parquet_b64 = payload.get("parquet_b64")
        arrow_ipc_b64 = payload.get("arrow_ipc_b64")
        parquet_path = payload.get("parquet_path")
        ctx = payload.get("ctx", {})
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Invalid input: {e}\n")
        return 1

    try:
        if arrow_ipc_b64:
            ipc_bytes = base64.b64decode(arrow_ipc_b64)
            with pa.ipc.open_stream(ipc_bytes) as reader:
                table = reader.read_all()
            df = table.to_pandas()
        elif parquet_b64:
            data = base64.b64decode(parquet_b64)
            df = pd.read_parquet(io.BytesIO(data))
        elif parquet_path:
            df = pd.read_parquet(parquet_path)
        else:
            raise ValueError("Missing parquet_b64 or parquet_path")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Failed to read parquet: {e}\n")
        return 1

    globs = _prepare_globals()
    locs = {}

    try:
        compiled = compile(code, filename="<user_code>", mode="exec")
        exec(compiled, globs, locs)
        run = globs.get("run") or locs.get("run")
        if not callable(run):
            raise RuntimeError("Missing function run(df, ctx)")
        result = run(df, ctx)
        if result is None:
            result = globs.get("RESULT")

        # Coerce common outputs into the expected dict shape
        if not isinstance(result, dict):
            if isinstance(result, pd.DataFrame):
                result = {"table": result.to_dict(orient="records"), "metrics": {}, "chartData": {}}
            elif isinstance(result, list):
                # Assume list of rows
                result = {"table": result, "metrics": {}, "chartData": {}}
            else:
                # Fallback to df preview
                result = _build_fallback_from_df(df, ctx)

        # Ensure required keys exist; fill from df when missing
        if "table" not in result or not isinstance(result.get("table"), list):
            result["table"] = df.head(int((ctx or {}).get("row_limit", 200))).to_dict(orient="records")
        if "metrics" not in result or not isinstance(result.get("metrics"), dict):
            result["metrics"] = {"rows": int(len(df)), "columns": int(len(df.columns))}
        if "chartData" not in result or not isinstance(result.get("chartData"), dict):
            # Only provide a fallback chart when explicitly requested
            try:
                q = str((ctx or {}).get("question") or "").lower()
            except Exception:
                q = ""
            wants_chart = any(tok in q for tok in ("chart", "plot", "graph", "visualization"))
            result["chartData"] = _build_fallback_from_df(df, ctx)["chartData"] if wants_chart else {}

        # Enforce explicit request and limits even if user code returned a chart
        try:
            q = str((ctx or {}).get("question") or "").lower()
        except Exception:
            q = ""
        wants_chart = any(tok in q for tok in ("chart", "plot", "graph", "visualization"))
        if not wants_chart:
            result["chartData"] = {}

        # Cheap quality gate for common analytic intents
        try:
            q = str((ctx or {}).get("question") or "").lower()
            intent_tokens = ("compare", "variance", "var", "difference", "diff", "change", "trend", "delta")
            requires_computed = any(tok in q for tok in intent_tokens)
            if requires_computed and result.get("table"):
                table_cols = set(result["table"][0].keys()) if result["table"] else set()
                raw_cols = set(map(str, df.columns.tolist()))
                computed_cols = table_cols - raw_cols
                if len(computed_cols) == 0:
                    # Clean UX error result instead of a generic preview
                    result = {"table": [], "metrics": {}, "chartData": {}, "error": "Result appears generic; no computed columns for requested analysis."}
        except Exception:
            pass
        
        # --- NEW: Sanitize the entire result object for Firestore/JSON compatibility ---
        sanitized_result = sanitize_for_firestore(result)
        
        sys.stdout.write(json.dumps(sanitized_result, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Runtime error: {e}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())