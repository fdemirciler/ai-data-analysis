from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

# Ensure orchestrator modules are importable
ROOT = Path(__file__).resolve().parents[2]
ORCH_PATH = ROOT / "backend" / "functions" / "orchestrator"
if str(ORCH_PATH) not in sys.path:
    sys.path.insert(0, str(ORCH_PATH))

import analysis_toolkit  # noqa: E402

try:
    import google.generativeai as genai  # noqa: E402
except Exception as e:
    raise RuntimeError("google-generativeai must be installed to build embeddings") from e


MODEL = os.getenv("EMBED_MODEL", "models/text-embedding-004")
API_KEY = os.getenv("GEMINI_API_KEY")
ASSETS_DIR = ORCH_PATH / "assets"
EMBED_FILE = ASSETS_DIR / "embeddings.json"


def _ensure_client() -> None:
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY environment variable is required to build embeddings.")
    genai.configure(api_key=API_KEY)


def _extract_embedding_vector(result: Any) -> List[float]:
    # SDK may return {"embedding": {"values": [...]}} or {"embedding": [...]} depending on version
    if isinstance(result, dict) and "embedding" in result:
        emb = result["embedding"]
        if isinstance(emb, dict) and "values" in emb:
            return list(emb.get("values") or [])
        if isinstance(emb, (list, tuple)):
            return list(emb)
    # Some versions return object-like responses with attribute access
    try:
        emb = getattr(result, "embedding", None)
        if emb is not None:
            vals = getattr(emb, "values", None)
            if vals is not None:
                return list(vals)
            if isinstance(emb, (list, tuple)):
                return list(emb)
    except Exception:
        pass
    raise RuntimeError("Could not extract embedding vector from response.")


def build_tool_embeddings() -> Dict[str, Any]:
    _ensure_client()

    vectors: Dict[str, List[float]] = {}
    thresholds: Dict[str, float] = {}

    for tool in analysis_toolkit.TOOLS_SPEC:
        name = tool.get("name")
        if not name:
            continue
        examples = list(tool.get("examples", []) or [])
        desc = str(tool.get("description") or "").strip()
        if not examples and not desc:
            continue

        sample_vectors: List[List[float]] = []
        for ex in examples:
            try:
                res = genai.embed_content(model=MODEL, content=str(ex))
                vec = _extract_embedding_vector(res)
                sample_vectors.append(vec)
            except Exception as e:
                # Skip failed example but continue
                sys.stderr.write(f"Warn: embedding example failed for {name}: {e}\n")
        # Optionally blend description for stability
        if desc:
            try:
                res = genai.embed_content(model=MODEL, content=desc)
                dvec = _extract_embedding_vector(res)
                sample_vectors.append(dvec)
            except Exception:
                pass

        if not sample_vectors:
            continue

        # Mean vector
        mat = np.array(sample_vectors, dtype=float)
        mean_vec = np.mean(mat, axis=0)
        vectors[name] = mean_vec.astype(float).tolist()

        # Initial per-intent thresholds (tunable later). Conservative defaults.
        # These are optional and can be overridden by env at runtime.
        default_thr = {
            "run_aggregation": 0.82,
            "sum_column": 0.80,
            "run_variance": 0.83,
            "value_counts": 0.78,
            "pivot_table": 0.85,
            "run_describe": 0.75,
        }.get(name)
        if default_thr is not None:
            thresholds[name] = float(default_thr)

    if not ASSETS_DIR.exists():
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # Determine embedding dimension if available
    dim = 0
    try:
        any_vec = next(iter(vectors.values()))
        dim = len(any_vec)
    except Exception:
        pass

    payload = {
        "model": MODEL,
        "dim": dim,
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "vectors": vectors,
        "thresholds": thresholds,
    }

    with open(EMBED_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    print(f"✓ Wrote embeddings for {len(vectors)} tools to {EMBED_FILE}")
    return payload


if __name__ == "__main__":
    build_tool_embeddings()
