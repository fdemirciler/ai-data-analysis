from __future__ import annotations

import os
import re
from typing import Any, Dict, List

import google.generativeai as genai

_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
_API_KEY = os.getenv("GEMINI_API_KEY", "")

_configured = False
_model = None


def _ensure_model():
    global _configured, _model
    if not _configured:
        if not _API_KEY:
            raise RuntimeError("GEMINI_API_KEY not set")
        genai.configure(api_key=_API_KEY)
        _model = genai.GenerativeModel(_MODEL_NAME)
        _configured = True
    return _model


def generate_analysis_code(question: str, schema_snippet: str, sample_rows: list[dict], row_limit: int = 200) -> str:
    """Ask Gemini to produce Python code implementing def run(df, ctx): -> RESULT.

    Strict mode: the response MUST contain a single fenced Python block with a valid
    `def run(df, ctx):` implementation. If not present, we raise to let the caller
    fail fast (no generic preview fallback).
    """
    model = _ensure_model()
    sample_preview = sample_rows[: min(len(sample_rows), 10)]
    
    # Strict prompt: produce exactly one fenced python code block (no narration).
    prompt = (
        "You are an expert Python data analyst. Write a single function to answer the user's question.\n\n"
        "OUTPUT REQUIREMENTS (STRICT):\n"
        "- Return ONLY one fenced Python code block starting with ```python and ending with ``` (no extra text).\n"
        "- The block must define: def run(df, ctx): -> dict\n"
        "- The returned dict MUST have keys: 'table' (list[dict]), 'metrics' (dict), 'chartData' (dict).\n"
        "- If required columns are missing, return {'error': 'missing column X'} with empty table/metrics/chartData.\n"
        "- Round floats to <=3 decimals and avoid NaN/Inf (use None).\n"
        "- Allowed imports: pandas as pd, numpy as np, math, json.\n"
        "- Only produce a chart if the question explicitly asks (chart/plot/graph/visualization); otherwise chartData should be empty (e.g., {'kind':'bar','labels':[],'series':[]}).\n\n"
        f"SCHEMA:\n{schema_snippet}\n\n"
        f"SAMPLE ROWS:\n{sample_preview}\n\n"
        f"USER QUESTION: \"{question}\"\n\n"
        "Return the code block now:"
    )

    resp = model.generate_content(
        prompt,
        generation_config={"max_output_tokens": 2048, "temperature": 0.0},
    )
    text = ""
    # Be robust to safety blocks / empty candidates
    try:
        # Prefer using .text, but guard when candidates are empty
        if getattr(resp, "candidates", None):
            try:
                text = resp.text or ""
            except Exception:
                # Manually assemble text from parts
                for c in resp.candidates:
                    content = getattr(c, "content", None)
                    parts = getattr(content, "parts", None) if content else None
                    if parts:
                        snippets = []
                        for p in parts:
                            t = getattr(p, "text", None)
                            if t:
                                snippets.append(t)
                        text = "\n".join(snippets)
                        if text:
                            break
        else:
            # No candidates collection available
            try:
                text = resp.text or ""
            except Exception:
                text = ""
    except Exception:
        text = ""

    code = _extract_code_block(text)
    if not code or "def run(" not in code:
        raise RuntimeError("MISSING_CODE_BLOCK")
    return code


def generate_summary(question: str, table_head: list[dict], metrics: dict, code: str | None = None) -> str:
    """Generates a data-driven summary by interpreting the analysis results.

    Includes the generated code (if available) to improve relevance.
    """
    model = _ensure_model()
    preview = table_head[: min(len(table_head), 5)]
    
    # --- PROMPT ENHANCEMENT for Interpretation ---
    prompt = (
        "You are a financial data analyst. Your task is to interpret the results of a data analysis that was just performed. "
        "Do not describe the code or the calculation method. Focus only on what the data itself reveals about the user's question.\n\n"
        "Provide a concise, one-paragraph summary highlighting the most important trends, variances, or key figures from the data. "
        "If there are significant changes or anomalies in the results, mention them.\n\n"
        f"USER'S ORIGINAL QUESTION: \"{question}\"\n\n"
        f"ANALYSIS RESULTS - TABLE SAMPLE:\n{preview}\n\n"
        f"ANALYSIS RESULTS - KEY METRICS:\n{metrics}\n\n"
        + (f"GENERATED CODE (for context):\n```python\n{(code or '')[:800]}\n```\n\n" if code else "")
        + "YOUR INTERPRETATION:"
    )
    # --- END PROMPT ENHANCEMENT ---

    resp = model.generate_content(prompt, generation_config={"max_output_tokens": 2048, "temperature": 0.3})
    text = ""
    try:
        text = (resp.text or "").strip()
    except Exception:
        text = ""

    if text:
        return text

    # --- Data-driven fallback when the model returns empty/blocked text ---
    try:
        rows_val = int(metrics.get("rows")) if isinstance(metrics, dict) and metrics.get("rows") is not None else None
    except Exception:
        rows_val = None
    try:
        cols_val = int(metrics.get("columns")) if isinstance(metrics, dict) and metrics.get("columns") is not None else None
    except Exception:
        cols_val = None

    cols_preview: list[str] = []
    try:
        if isinstance(table_head, list) and len(table_head) > 0 and isinstance(table_head[0], dict):
            cols_preview = list(table_head[0].keys())[:6]
    except Exception:
        cols_preview = []

    parts: list[str] = []
    if question:
        parts.append(f"Question: {question.strip()}")
    if rows_val is not None and cols_val is not None:
        parts.append(f"Dataset shape: {rows_val} rows × {cols_val} columns.")
    elif rows_val is not None:
        parts.append(f"Rows: {rows_val}.")
    elif cols_val is not None:
        parts.append(f"Columns: {cols_val}.")
    if cols_preview:
        parts.append("Columns preview: " + ", ".join(map(str, cols_preview)) + ".")

    fallback = " ".join(parts).strip()
    if not fallback:
        fallback = "No textual summary available. See the table for details."
    return fallback


def _extract_code_block(text: str) -> str:
    # Prefer ```python ... ``` blocks
    m = re.search(r"```python\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Fallback: any fenced block
    m = re.search(r"```\s*(.*?)```", text, flags=re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: raw text
    return text.strip()


def generate_code_and_summary(question: str, schema_snippet: str, sample_rows: list[dict], row_limit: int = 200) -> tuple[str, str]:
    """Return (code, summary) using a single fused call when GEMINI_FUSED is truthy."""
    fused = os.getenv("GEMINI_FUSED", "1").lower() not in ("0", "false", "no")
    if not fused:
        code = generate_analysis_code(question, schema_snippet, sample_rows, row_limit=row_limit)
        summary = "Analysis planned. Executed results will follow." # Placeholder summary
        return code, summary

    model = _ensure_model()
    sample_preview = sample_rows[: min(len(sample_rows), 10)]
    
    # Strict two-block format: code and a result schema example. No narration outside blocks.
    prompt = (
        "You are an expert Python data analyst. Produce code in a strict two-block format.\n\n"
        "RULES FOR THE CODE BLOCK:\n"
        "1. The function signature MUST be `def run(df, ctx):`.\n"
        "2. The function MUST return a dictionary with keys: 'table', 'metrics', and 'chartData'.\n"
        "3. Round floats to <=3 decimals; avoid NaN/Inf by using None.\n"
        "4. Allowed imports: pandas as pd, numpy as np, math, json.\n"
        "5. Only generate a chart if the user's question explicitly asks; otherwise return empty chartData.\n\n"
        "OUTPUT FORMAT (MUST BE EXACTLY THIS):\n"
        "[CODE_START]\n"
        "```python\n"
        "# only the def run(df, ctx): implementation here\n"
        "```\n"
        "[CODE_END]\n"
        "[RESULT_SCHEMA_START]\n"
        "{\n  \"table\": [{\"...\": \"...\"}], \n  \"metrics\": {\"...\": 0}, \n  \"chartData\": {\"kind\": \"bar\", \"labels\": [], \"series\": []}\n}\n"
        "[RESULT_SCHEMA_END]\n\n"
        "--- START OF DATA ---\n"
        f"Schema:\n{schema_snippet}\n\n"
        f"Sample rows:\n{sample_preview}\n\n"
        f"User question: {question}\n"
    )
    
    resp = model.generate_content(
        prompt,
        generation_config={"max_output_tokens": 2048, "temperature": 0.0},
    )
    text = ""
    try:
        text = resp.text or ""
    except Exception:
        text = ""

    # Parse structured markers first (fail fast if missing)
    code = ""
    try:
        m_code_block = re.search(r"\[CODE_START\](.*?)\[CODE_END\]", text, flags=re.DOTALL | re.IGNORECASE)
        m_result = re.search(r"\[RESULT_SCHEMA_START\](.*?)\[RESULT_SCHEMA_END\]", text, flags=re.DOTALL | re.IGNORECASE)
        if not m_code_block or not m_result:
            raise RuntimeError("MISSING_REQUIRED_BLOCKS")
        code_section = m_code_block.group(1)
        code = _extract_code_block(code_section)
        if not code or "def run(" not in code:
            raise RuntimeError("MISSING_CODE_BLOCK")
    except Exception as e:
        # Propagate to orchestrator to emit CODEGEN_FAILED
        raise

    # We don't need a pre-summary; provide a small placeholder.
    summary = "Analysis planned. Executed results will follow."
    return code, summary

