from __future__ import annotations

import os
import re
from typing import Any, Dict, List

import google.generativeai as genai

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MODEL_NAME = "gemini-2.5-flash"  # As requested
_API_KEY = os.getenv("GEMINI_API_KEY", "")

_MAX_TOKENS = 4096
_TEMPERATURE = 0.2

_configured = False
_model = None


def _ensure_model():
    """Ensure the Gemini client is configured and return the model."""
    global _configured, _model
    if not _configured:
        if not _API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set")
        genai.configure(api_key=_API_KEY)
        _model = genai.GenerativeModel(_MODEL_NAME)
        _configured = True
    return _model


# ---------------------------------------------------------------------------
# Core: Generate Analysis Code
# ---------------------------------------------------------------------------

def generate_analysis_code(
    question: str,
    schema_snippet: str,
    sample_rows: list[dict],
    row_limit: int = 200
) -> str:
    """
    Ask Gemini to produce Python code, with a one-time auto-repair attempt.
    This function is primarily used for the repair loop.
    """
    model = _ensure_model()
    sample_preview = sample_rows[: min(len(sample_rows), 10)]

    prompt = (
        "You are an expert Python data analyst. Write a single Python function "
        "`def run(df, ctx):` to answer the user's question about the dataset.\n\n"
        "OUTPUT RULES (STRICT):\n"
        "- Return ONLY one fenced Python code block starting with ```python.\n"
        "- The function MUST return a dict with EXACT keys: 'table' (list of dict rows answering the question),\n"
        "  'metrics' (dict of key figures), and 'chartData' (object with keys: 'kind', 'labels', 'series' = list of {label, data}).\n"
        "- Do NOT return 'tables' or 'charts' keys. Use 'table' and 'chartData' only.\n"
        "- Respect ctx.get('row_limit', 200) when returning 'table'.\n"
        "- Use robust numeric handling: prefer pd.to_numeric(..., errors='coerce') and select_dtypes(include=[np.number]) for stats.\n"
        "- Never use complex dtype or astype(complex).\n"
        "- If a chart is appropriate, populate 'chartData' with non-empty labels and numeric series; else return empty {}.\n"
        "- Allowed imports: pandas, numpy, matplotlib, seaborn, math, statistics, json, io, "
        "itertools, functools, collections, re, datetime, base64.\n\n"
        f"SCHEMA:\n{schema_snippet}\n\n"
        f"SAMPLE ROWS:\n{sample_preview}\n\n"
        f"USER QUESTION:\n\"{question}\"\n\n"
        "Return only the fenced Python code block now."
    )

    resp = model.generate_content(
        prompt,
        generation_config={
            "max_output_tokens": _MAX_TOKENS,
            "temperature": _TEMPERATURE,
        },
    )

    text = _safe_response_text(resp)
    code = _extract_code_block(text)

    # Accept 'def run (df, ctx):' with arbitrary whitespace
    if not code or not re.search(r"def\s+run\s*\(", code):
        raise RuntimeError("CODEGEN_FAILED: Missing valid 'def run(df, ctx):' implementation.")
    return code


# ---------------------------------------------------------------------------
# Generate Summary
# ---------------------------------------------------------------------------

def generate_summary(
    question: str,
    table_head: list[dict],
    metrics: dict,
    code: str | None = None
) -> str:
    """Generate a concise, data-driven summary from analysis results."""
    model = _ensure_model()
    preview = table_head[: min(len(table_head), 5)]

    prompt = (
        "You are a financial data analyst. Interpret the analysis results below. "
        "Focus on trends, anomalies, or key figures; do NOT describe the code.\n\n"
        f"USER QUESTION: \"{question}\"\n\n"
        f"TABLE PREVIEW:\n{preview}\n\n"
        f"KEY METRICS:\n{metrics}\n\n"
        "Now write a one-paragraph interpretation of the data:"
    )

    try:
        resp = model.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": _MAX_TOKENS,
                "temperature": _TEMPERATURE,
            },
        )
        text = _safe_response_text(resp).strip()
        if text:
            return text
    except Exception:
        # Fallthrough to generate a fallback summary if API fails
        pass

    # Fallback: minimal textual info if API fails or returns empty
    parts = []
    if question: parts.append(f"Question: {question}")
    if metrics: parts.append(f"Metrics: {list(metrics.keys())[:5]}")
    return " ".join(parts) or "No textual summary available."


# ---------------------------------------------------------------------------
# Fused: Generate Code + Summary in a Single Call
# ---------------------------------------------------------------------------

def generate_code_and_summary(
    question: str,
    schema_snippet: str,
    sample_rows: list[dict],
    row_limit: int = 200
) -> tuple[str, str]:
    """
    Return (code, summary) using a single Gemini call, with a one-time repair loop.
    """
    fused = os.getenv("GEMINI_FUSED", "0").lower() not in ("0", "false", "no")
    if not fused:
        code = generate_analysis_code(question, schema_snippet, sample_rows, row_limit=row_limit)
        return code, "Analysis planned. Executed results will follow."

    model = _ensure_model()
    sample_preview = sample_rows[: min(len(sample_rows), 10)]

    prompt = (
        "You are an expert Python data analyst.\n\n"
        "Provide one fenced Python code block implementing `def run(df, ctx):`.\n\n"
        "CODE REQUIREMENTS (STRICT):\n"
        "- MUST return a dict with EXACT keys: 'table' (list[dict]), 'metrics' (dict), 'chartData' (kind, labels, series).\n"
        "- Do NOT return 'tables' or 'charts'.\n"
        "- Respect ctx.get('row_limit', 200). Use robust numeric handling; avoid complex dtype.\n"
        "- Allowed imports: pandas, numpy, matplotlib, seaborn, math, statistics, json, io, "
        "itertools, functools, collections, re, datetime, base64.\n\n"
        f"--- DATA CONTEXT ---\nSchema: {schema_snippet}\nSample rows: {sample_preview}\n\n"
        f"--- QUESTION ---\n\"{question}\"\n\n"
        "Return only the Python code block."
    )

    resp = model.generate_content(
        prompt,
        generation_config={
            "max_output_tokens": _MAX_TOKENS,
            "temperature": _TEMPERATURE,
        },
    )

    text = _safe_response_text(resp)
    code = _extract_code_block(text)
    
    # One-time repair attempt if initial extraction fails
    if not code:
        feedback_prompt = (
            "Your previous response was not formatted correctly. "
            f"Please regenerate the response for the following question: \"{question}\"\n\n"
            "Return a one-sentence summary, then a single, valid, fenced Python code block "
            "defining `def run(df, ctx):`."
        )
        retry_resp = model.generate_content(
            feedback_prompt,
            generation_config={
                "max_output_tokens": _MAX_TOKENS,
                "temperature": 0.0, # Use 0 temp for deterministic repair
            },
        )
        text = _safe_response_text(retry_resp)
        code = _extract_code_block(text)

    # If code extraction still fails, return the raw text for the orchestrator's repair loop.
    if not code:
        return "", text

    summary = "Analysis planned. Executed results will follow."
    return code, summary


# ---------------------------------------------------------------------------
# Repair Code given Runtime Error
# ---------------------------------------------------------------------------

def repair_code(
    question: str,
    schema_snippet: str,
    sample_rows: list[dict],
    previous_code: str,
    runtime_error: str,
    row_limit: int = 200,
) -> str:
    """Ask Gemini to repair previously generated code given a runtime error message."""
    model = _ensure_model()
    sample_preview = sample_rows[: min(len(sample_rows), 10)]

    prompt = (
        "You previously wrote Python analysis code which raised a runtime error. "
        "Repair the code. Maintain the same intent, and follow these strict rules.\n\n"
        "RULES (STRICT):\n"
        "- Implement `def run(df, ctx):` and return a dict with EXACT keys: 'table' (list[dict]), 'metrics' (dict), 'chartData'.\n"
        "- Do NOT return 'tables' or 'charts'. Use 'table' and 'chartData' only.\n"
        "- Respect ctx.get('row_limit', 200) for the size of 'table'.\n"
        "- Use robust numeric handling: prefer pd.to_numeric(..., errors='coerce'), select_dtypes(include=[np.number]).\n"
        "- Never use complex dtype or astype(complex).\n"
        "- Allowed imports: pandas, numpy, matplotlib, seaborn, math, statistics, json, io, "
        "itertools, functools, collections, re, datetime, base64.\n\n"
        f"RUNTIME ERROR: {runtime_error}\n\n"
        f"PREVIOUS CODE:\n```python\n{previous_code}\n```\n\n"
        f"SCHEMA:\n{schema_snippet}\n\n"
        f"SAMPLE ROWS:\n{sample_preview}\n\n"
        f"USER QUESTION:\n\"{question}\"\n\n"
        "Return only the repaired Python code block."
    )

    resp = model.generate_content(
        prompt,
        generation_config={
            "max_output_tokens": _MAX_TOKENS,
            "temperature": 0.0,
        },
    )
    text = _safe_response_text(resp)
    code = _extract_code_block(text)
    if not code or not re.search(r"def\s+run\s*\(", code):
        raise RuntimeError("REPAIR_FAILED: Missing valid 'def run(df, ctx):' implementation.")
    return code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_response_text(resp) -> str:
    """Safely extract text from Gemini responses, handling potential exceptions."""
    try:
        if getattr(resp, "text", None):
            return resp.text or ""
        if getattr(resp, "candidates", None):
            for c in resp.candidates:
                content = getattr(c, "content", None)
                parts = getattr(content, "parts", None) if content else None
                if parts:
                    return "".join(p.text for p in parts if hasattr(p, "text"))
    except Exception:
        return ""
    return ""


def _extract_code_block(text: str) -> str:
    """Extract a Python code block robustly from a response."""
    # 1. Prefer fenced python block
    m = re.search(r"```python\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        code = m.group(1).strip()
        if re.search(r"def\s+run\s*\(", code):
            return code

    # 2. Fallback to any fenced block
    m = re.search(r"```(.*?)```", text, flags=re.DOTALL)
    if m:
        code = m.group(1).strip()
        if re.search(r"def\s+run\s*\(", code):
            return code

    # 3. Heuristic fallback: find the start of the function definition
    m = re.search(r"(def\s+run\s*\(.*)", text, flags=re.DOTALL)
    if m:
        return m.group(1).strip()

    return ""

