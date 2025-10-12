#!/usr/bin/env python3
"""
Build env files for orchestrator from backend/config.yaml.
- Merges: default + orchestrator (+ optional overlay 'prod').
- Validates keys against an allowlist aligned to config.py.
- Flattens nested maps (e.g., fastpath_disable_column_prune) into env vars.
- Outputs:
  - backend/env.orchestrator.yaml (for --env-vars-file)
  - backend/.env.orchestrator.example (KEY=VALUE lines, non-secret)
  - backend/deploy.orchestrator.flags.json (deploy flags for PS script)

Usage:
  py -3 scripts/build_envs.py --service orchestrator [--overlay prod]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Any

try:
    import yaml  # type: ignore
except Exception:
    raise SystemExit("PyYAML is required. Install with: pip install pyyaml")

BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BACKEND_DIR / "config.yaml"
ENV_YAML_PATH = BACKEND_DIR / "env.orchestrator.yaml"
ENV_DOTENV_EXAMPLE = BACKEND_DIR / ".env.orchestrator.example"
DEPLOY_FLAGS_JSON = BACKEND_DIR / "deploy.orchestrator.flags.json"

ALLOWED_PREFIXES = ("FASTPATH_DISABLE_COLUMN_PRUNE_",)
ALLOWED_ENV_KEYS = {
    # Core
    "GCP_PROJECT","FILES_BUCKET","RUNTIME_SERVICE_ACCOUNT",
    # Timeouts/limits
    "SSE_PING_INTERVAL_SECONDS","CHAT_HARD_TIMEOUT_SECONDS","CHAT_REPAIR_TIMEOUT_SECONDS",
    "CODEGEN_TIMEOUT_SECONDS","CLASSIFIER_TIMEOUT_SECONDS","MAX_FASTPATH_ROWS",
    "FORCE_FALLBACK_MIN_ROWS","MAX_CHART_POINTS",
    # Flags/Router/UI
    "FASTPATH_ENABLED","FALLBACK_ENABLED","CODE_RECONSTRUCT_ENABLED",
    "LOG_CLASSIFIER_RESPONSE","MIRROR_COMMAND_TO_FIRESTORE","MIN_FASTPATH_CONFIDENCE",
    "ORCH_IPC_MODE","TOOLKIT_VERSION","PRESENTATIONAL_CODE_STYLE","ALLOWED_ORIGINS",
    # Gemini (non-secret only)
    "GEMINI_MODEL_NAME","GEMINI_MAX_TOKENS","GEMINI_TEMPERATURE","GEMINI_FUSED",
    "CLASSIFIER_MODEL_OVERRIDE","PRESENTATIONAL_CODE_TEMPERATURE",
    # Worker/Sandbox
    "CODE_TIMEOUT","CODE_MAX_MEMORY_BYTES","SANDBOX_MODE",
    # Embedding router
    "EMBED_ROUTER_ENABLED","EMBED_MODEL","EMBED_TIMEOUT_SECONDS","EMBED_THRESHOLD_DEFAULT",
}
# Secrets deliberately excluded (example only): GEMINI_API_KEY
DEPLOY_FLAG_KEYS = ("GCP_PROJECT","GCP_REGION","RUNTIME_SERVICE_ACCOUNT","MEMORY","CPU","FILES_BUCKET","ALLOWED_ORIGINS")


def _merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a or {})
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)  # type: ignore
        else:
            out[k] = v
    return out


def _flatten(merged: Dict[str, Any]) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for k, v in merged.items():
        if k == "fastpath_disable_column_prune" and isinstance(v, dict):
            for subk, subv in v.items():
                env[f"FASTPATH_DISABLE_COLUMN_PRUNE_{str(subk).upper()}"] = str(subv)
            continue
        if isinstance(v, (dict, list)):
            continue
        env[str(k).upper()] = "" if v is None else str(v)
    return env


def _validate_env_keys(env_map: Dict[str, str]) -> None:
    invalid = []
    for k in env_map.keys():
        if k in ALLOWED_ENV_KEYS:
            continue
        if any(k.startswith(p) for p in ALLOWED_PREFIXES):
            continue
        invalid.append(k)
    if invalid:
        raise SystemExit("Invalid/unsupported keys: " + ", ".join(sorted(invalid)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", required=True, choices=["orchestrator"])
    ap.add_argument("--overlay", choices=["prod"], default=None)
    args = ap.parse_args()

    if not CONFIG_PATH.exists():
        raise SystemExit(f"Missing config file: {CONFIG_PATH}")

    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    defaults = cfg.get("default", {}) or {}
    svc = cfg.get(args.service, {}) or {}
    merged = _merge(defaults, svc)
    if args.overlay:
        merged = _merge(merged, cfg.get(args.overlay, {}) or {})

    # Flatten all merged keys
    env_all = _flatten(merged)
    # Split: env vars vs deploy-only flags
    env_only = {k: v for k, v in env_all.items() if (k in ALLOWED_ENV_KEYS) or any(k.startswith(p) for p in ALLOWED_PREFIXES)}
    # Validate only env var keys
    _validate_env_keys(env_only)
    # Additional guard: detect unknown keys not accounted for by env allowlist or deploy flags
    unknown = [k for k in env_all.keys() if (k not in env_only) and (k not in DEPLOY_FLAG_KEYS)]
    if unknown:
        raise SystemExit("Invalid/unsupported keys: " + ", ".join(sorted(unknown)))

    # forbid secret-like keys
    forbidden = [k for k in env_only if k.endswith(("_KEY","_TOKEN","_SECRET"))]
    if forbidden:
        raise SystemExit("Forbidden secret-like keys in YAML: " + ", ".join(sorted(forbidden)))

    # Write env YAML
    ENV_YAML_PATH.write_text(yaml.safe_dump(env_only, sort_keys=True), encoding="ascii")

    # Write deploy flags JSON for PS
    flags = {k: env_all.get(k, "") for k in DEPLOY_FLAG_KEYS}
    DEPLOY_FLAGS_JSON.write_text(json.dumps(flags, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
