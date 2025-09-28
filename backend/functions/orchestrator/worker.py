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
import sys
import types

import pandas as pd  # noqa: F401  (provided as pd)
import numpy as np  # noqa: F401  (provided as np)

ALLOWED_IMPORTS = {"pandas", "numpy", "math", "json"}


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
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "filter",
        "float",
        "int",
        "len",
        "list",
        "map",
        "max",
        "min",
        "pow",
        "range",
        "round",
        "set",
        "slice",
        "sorted",
        "str",
        "sum",
        "zip",
        "print",  # benign
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


def main() -> int:
    global _orig_import  # noqa: PLW0603
    import builtins as _builtins

    _orig_import = _builtins.__import__

    try:
        payload = json.load(sys.stdin)
        code = payload.get("code", "")
        parquet_path = payload["parquet_path"]
        ctx = payload.get("ctx", {})
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Invalid input: {e}\n")
        return 1

    try:
        df = pd.read_parquet(parquet_path)
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
        if not isinstance(result, dict):
            raise RuntimeError("run() must return a dict")
        # Basic shape checks
        if "table" not in result or "chartData" not in result:
            raise RuntimeError("RESULT must include 'table' and 'chartData'")
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Runtime error: {e}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
