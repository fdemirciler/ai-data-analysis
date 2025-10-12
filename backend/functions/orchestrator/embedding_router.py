from __future__ import annotations

import os
import json
from functools import lru_cache
from typing import Dict, Tuple, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

import numpy as np

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None  # type: ignore

import config


def _assets_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "embeddings.json"


@lru_cache(maxsize=1)
def load_tool_embeddings() -> Tuple[Dict[str, list], Dict[str, float]]:
    p = _assets_path()
    if not p.exists():
        return {}, {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        vectors = dict((data.get("vectors") or {}))
        thresholds = dict((data.get("thresholds") or {}))
        return vectors, thresholds
    except Exception:
        return {}, {}


def _extract_embedding_vector(result) -> Optional[list]:
    if result is None:
        return None
    if isinstance(result, dict) and "embedding" in result:
        emb = result["embedding"]
        if isinstance(emb, dict) and "values" in emb:
            return list(emb.get("values") or [])
        if isinstance(emb, (list, tuple)):
            return list(emb)
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
    return None


def embed_query_safe(query: str, model: Optional[str] = None, timeout_s: Optional[float] = None) -> Tuple[Optional[list], Optional[str]]:
    mdl = model or config.EMBED_MODEL
    tmo = float(timeout_s if timeout_s is not None else config.EMBED_TIMEOUT_SECONDS)

    if genai is None:
        return None, "error: generativeai not available"
    api_key = config.GEMINI_API_KEY
    if not api_key:
        return None, "error: GEMINI_API_KEY not set"
    try:
        genai.configure(api_key=api_key)
    except Exception:
        pass

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(genai.embed_content, model=mdl, content=query)
        try:
            res = fut.result(timeout=tmo)
            vec = _extract_embedding_vector(res)
            if not vec:
                return None, "error: empty embedding"
            return vec, None
        except FuturesTimeout:
            return None, "timeout"
        except Exception as e:
            return None, f"error: {e}"


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def get_embed_threshold(tool_name: str) -> float:
    env_key = f"EMBED_THRESHOLD_{(tool_name or '').upper()}"
    v = os.getenv(env_key)
    if v is not None:
        try:
            return float(v)
        except Exception:
            pass
    _, thresholds = load_tool_embeddings()
    if tool_name in thresholds:
        try:
            return float(thresholds[tool_name])
        except Exception:
            pass
    return float(config.EMBED_THRESHOLD_DEFAULT)


def semantic_route(query: str, model: Optional[str] = None, timeout_s: Optional[float] = None) -> Tuple[Optional[str], float]:
    vec, err = embed_query_safe(query, model=model, timeout_s=timeout_s)
    if vec is None:
        return None, 0.0
    vectors, _ = load_tool_embeddings()
    if not vectors:
        return None, 0.0
    q = np.array(vec, dtype=float)
    best_name: Optional[str] = None
    best_score: float = -1.0
    for name, v in vectors.items():
        t = np.array(v, dtype=float)
        s = cosine_similarity(q, t)
        if s > best_score:
            best_score = s
            best_name = name
    if best_name is None:
        return None, 0.0
    return best_name, float(best_score)
