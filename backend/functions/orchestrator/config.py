"""
Centralized configuration for the orchestrator.
All environment-derived settings are defined here and imported by modules.
"""
from __future__ import annotations

import os
from typing import Set
try:
    import yaml  # type: ignore
except Exception:
    yaml = None

import analysis_toolkit


def _load_yaml_defaults() -> dict:
    val = os.getenv("USE_CONFIG_YAML_LOCAL", "0").lower()
    if val not in ("1", "true", "yes", "y", "on"):
        return {}
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.yaml")
    if not os.path.exists(cfg_path) or yaml is None:
        return {}
    try:
        data = yaml.safe_load(open(cfg_path, "r", encoding="utf-8")) or {}
        d = dict(data.get("default", {}) or {})
        o = dict(data.get("orchestrator", {}) or {})
        merged = {}
        merged.update({str(k).upper(): v for k, v in d.items()})
        merged.update({str(k).upper(): v for k, v in o.items()})
        # flatten fastpath_disable_column_prune
        fp = o.get("fastpath_disable_column_prune") if isinstance(o, dict) else None
        if isinstance(fp, dict):
            for sk, sv in fp.items():
                merged[f"FASTPATH_DISABLE_COLUMN_PRUNE_{str(sk).upper()}"] = sv
        return merged
    except Exception:
        return {}


_YAML_DEFAULTS = _load_yaml_defaults()


def _getenv(key: str, default: str) -> str:
    v = os.getenv(key)
    if v is not None:
        return v
    if _YAML_DEFAULTS:
        yv = _YAML_DEFAULTS.get(key)
        if yv is not None:
            return str(yv)
    return default


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        val = str(_YAML_DEFAULTS.get(key)) if _YAML_DEFAULTS.get(key) is not None else None
        if val is None:
            return default
    return str(val).lower() in ("1", "true", "yes", "y", "on")


# ---------------------------------------------------------------------------
# Core project/bucket
# ---------------------------------------------------------------------------
PROJECT_ID: str = _getenv("GCP_PROJECT", "ai-data-analyser")
FILES_BUCKET: str = _getenv("FILES_BUCKET", "ai-data-analyser-files")
RUNTIME_SERVICE_ACCOUNT: str | None = (_getenv("RUNTIME_SERVICE_ACCOUNT", "") or None)

# ---------------------------------------------------------------------------
# Timeouts and limits
# ---------------------------------------------------------------------------
SSE_PING_INTERVAL_SECONDS: int = int(_getenv("SSE_PING_INTERVAL_SECONDS", "22"))
CHAT_HARD_TIMEOUT_SECONDS: int = int(_getenv("CHAT_HARD_TIMEOUT_SECONDS", "60"))
CHAT_REPAIR_TIMEOUT_SECONDS: int = int(_getenv("CHAT_REPAIR_TIMEOUT_SECONDS", "30"))
CODEGEN_TIMEOUT_SECONDS: int = int(_getenv("CODEGEN_TIMEOUT_SECONDS", "30"))
CLASSIFIER_TIMEOUT_SECONDS: int = int(_getenv("CLASSIFIER_TIMEOUT_SECONDS", "8"))
MAX_FASTPATH_ROWS: int = int(_getenv("MAX_FASTPATH_ROWS", "50000"))
FORCE_FALLBACK_MIN_ROWS: int = int(_getenv("FORCE_FALLBACK_MIN_ROWS", "500000"))
MAX_CHART_POINTS: int = int(_getenv("MAX_CHART_POINTS", "500"))

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
FASTPATH_ENABLED: bool = _env_bool("FASTPATH_ENABLED", True)
FALLBACK_ENABLED: bool = _env_bool("FALLBACK_ENABLED", True)
CODE_RECONSTRUCT_ENABLED: bool = _env_bool("CODE_RECONSTRUCT_ENABLED", True)
LOG_CLASSIFIER_RESPONSE: bool = _env_bool("LOG_CLASSIFIER_RESPONSE", False)
MIRROR_COMMAND_TO_FIRESTORE: bool = _env_bool("MIRROR_COMMAND_TO_FIRESTORE", False)

# ---------------------------------------------------------------------------
# Router / dispatcher
# ---------------------------------------------------------------------------
MIN_FASTPATH_CONFIDENCE: float = float(_getenv("MIN_FASTPATH_CONFIDENCE", "0.65"))
ORCH_IPC_MODE: str = _getenv("ORCH_IPC_MODE", "base64").lower()

# Embedding router (feature-flagged)
EMBED_ROUTER_ENABLED: bool = _env_bool("EMBED_ROUTER_ENABLED", False)
EMBED_MODEL: str = _getenv("EMBED_MODEL", "models/text-embedding-004")
EMBED_TIMEOUT_SECONDS: float = float(_getenv("EMBED_TIMEOUT_SECONDS", "1.5"))
EMBED_THRESHOLD_DEFAULT: float = float(_getenv("EMBED_THRESHOLD_DEFAULT", "0.83"))

# Toolkit version (default to analysis_toolkit.TOOLKIT_VERSION when not set)
TOOLKIT_VERSION: int = int(_getenv("TOOLKIT_VERSION", str(getattr(analysis_toolkit, "TOOLKIT_VERSION", 1))))

# ---------------------------------------------------------------------------
# UI/Presentation
# ---------------------------------------------------------------------------
PRESENTATIONAL_CODE_STYLE: str = _getenv("PRESENTATIONAL_CODE_STYLE", "educational")

# CORS
ALLOWED_ORIGINS: Set[str] = {
    o.strip()
    for o in (_getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,https://ai-data-analyser.web.app,https://ai-data-analyser.firebaseapp.com",
    ) or "").split(",")
    if o and o.strip()
}

# ---------------------------------------------------------------------------
# Gemini / LLM
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = _getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME: str = _getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")
GEMINI_MAX_TOKENS: int = int(_getenv("GEMINI_MAX_TOKENS", "4096"))
GEMINI_TEMPERATURE: float = float(_getenv("GEMINI_TEMPERATURE", "0.2"))
CLASSIFIER_TEMPERATURE: float = float(_getenv("CLASSIFIER_TEMPERATURE", "0.0"))
GEMINI_FUSED: bool = _env_bool("GEMINI_FUSED", False)
CLASSIFIER_MODEL_OVERRIDE: str = _getenv("CLASSIFIER_MODEL_OVERRIDE", "").strip()
PRESENTATIONAL_CODE_TEMPERATURE: float = float(_getenv("PRESENTATIONAL_CODE_TEMPERATURE", "0.1"))

# Common generation config (default)
GEMINI_GENERATION_CONFIG = {
    "max_output_tokens": GEMINI_MAX_TOKENS,
    "temperature": GEMINI_TEMPERATURE,
}

# Preferred settings for presentational code blocks (more deterministic by default)
PRESENTATIONAL_GENERATION_CONFIG = {
    "max_output_tokens": GEMINI_MAX_TOKENS,
    "temperature": PRESENTATIONAL_CODE_TEMPERATURE,
}

# ---------------------------------------------------------------------------
# Worker / Sandbox
# ---------------------------------------------------------------------------
CODE_TIMEOUT: int = int(_getenv("CODE_TIMEOUT", "60"))
CODE_MAX_MEMORY_BYTES: int = int(_getenv("CODE_MAX_MEMORY_BYTES", str(512 * 1024 * 1024)))
SANDBOX_MODE: str = _getenv("SANDBOX_MODE", "restricted").lower()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_config(logger=None) -> list[str]:
    """Validate key configuration values and optionally log warnings.

    Returns a list of warning messages.
    """
    issues: list[str] = []

    def _warn(msg: str) -> None:
        issues.append(msg)
        try:
            if logger and hasattr(logger, "warning"):
                logger.warning(msg)
        except Exception:
            pass

    # Bounds checks
    if MIN_FASTPATH_CONFIDENCE < 0.0 or MIN_FASTPATH_CONFIDENCE > 1.0:
        _warn(f"MIN_FASTPATH_CONFIDENCE out of [0,1]: {MIN_FASTPATH_CONFIDENCE}")
    for name, val in (
        ("SSE_PING_INTERVAL_SECONDS", SSE_PING_INTERVAL_SECONDS),
        ("CHAT_HARD_TIMEOUT_SECONDS", CHAT_HARD_TIMEOUT_SECONDS),
        ("CHAT_REPAIR_TIMEOUT_SECONDS", CHAT_REPAIR_TIMEOUT_SECONDS),
        ("CODEGEN_TIMEOUT_SECONDS", CODEGEN_TIMEOUT_SECONDS),
        ("CLASSIFIER_TIMEOUT_SECONDS", CLASSIFIER_TIMEOUT_SECONDS),
        ("MAX_FASTPATH_ROWS", MAX_FASTPATH_ROWS),
        ("FORCE_FALLBACK_MIN_ROWS", FORCE_FALLBACK_MIN_ROWS),
        ("MAX_CHART_POINTS", MAX_CHART_POINTS),
        ("GEMINI_MAX_TOKENS", GEMINI_MAX_TOKENS),
        ("CODE_TIMEOUT", CODE_TIMEOUT),
        ("CODE_MAX_MEMORY_BYTES", CODE_MAX_MEMORY_BYTES),
    ):
        try:
            if int(val) < 0:
                _warn(f"{name} should be >= 0 (got {val})")
        except Exception:
            _warn(f"{name} is not an integer-like value: {val}")

    if GEMINI_TEMPERATURE < 0.0 or GEMINI_TEMPERATURE > 2.0:
        _warn(f"GEMINI_TEMPERATURE unusual: {GEMINI_TEMPERATURE}")
    if PRESENTATIONAL_CODE_TEMPERATURE < 0.0 or PRESENTATIONAL_CODE_TEMPERATURE > 2.0:
        _warn(f"PRESENTATIONAL_CODE_TEMPERATURE unusual: {PRESENTATIONAL_CODE_TEMPERATURE}")

    if not GEMINI_API_KEY:
        _warn("GEMINI_API_KEY is not set (fallback paths will be used where applicable).")

    return issues


def fastpath_disable_column_prune(intent_name: str) -> bool:
    """Read per-intent column prune disable flag from env.
    Env var: FASTPATH_DISABLE_COLUMN_PRUNE_<INTENT>
    """
    key = f"FASTPATH_DISABLE_COLUMN_PRUNE_{intent_name}"
    return _env_bool(key, False)
