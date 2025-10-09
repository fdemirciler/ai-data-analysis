from __future__ import annotations

import os
import re
import json
from typing import Any, Dict, List

import pandas as pd
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


def _extract_any_python_block(text: str) -> str:
    """Extract any fenced python code block. If absent, any fenced block. Else raw text.

    Returns code content without fences.
    """
    if not isinstance(text, str) or not text:
        return ""
    m = re.search(r"```python\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*(.*?)```", text, flags=re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def generate_presentational_code(
    context: dict,
    schema_snippet: str,
    style: str = "educational",
) -> str:
    """Generate a human-readable, presentational pandas script.

    Rules (STRICT):
    - Do NOT define `def run(df, ctx)`; assume a DataFrame `df` already exists.
    - Focus on table-oriented transformations answering the analysis intent.
    - Do NOT include data loading/cleaning; end with: print(result_df.head()).
    - Return only the code (no fences in the returned string).

    Context must contain either:
    - {"command": {...}} from fastpath, or
    - {"question": "..."} from fallback.
    """
    model = _ensure_model()

    if not isinstance(context, dict) or ("command" not in context and "question" not in context):
        return "# Could not generate code: missing analysis context."

    if "command" in context and context.get("command"):
        try:
            analysis_context = f"ANALYSIS COMMAND:\n{json.dumps(context['command'], indent=2, ensure_ascii=False)}"
        except Exception:
            analysis_context = "ANALYSIS COMMAND: [unavailable]"
    else:
        analysis_context = f"USER QUESTION:\n\"{str(context.get('question') or '').strip()}\""

    base = (
        "You are an expert Python data analyst writing a tutorial-style script.\n"
        "Write a clean, self-contained pandas script that is easy for a beginner to understand.\n\n"
        "--- STRICT RULES ---\n"
        f"- Style: '{{style}}' (use clear variables and helpful comments).\n"
        "- Do NOT define def run(df, ctx). Assume a pandas DataFrame named `df` already exists.\n"
        "- Write only the transformation/aggregation logic relevant to the analysis.\n"
        "- Do NOT include any data loading or cleaning steps.\n"
        "- End the script by assigning the final table to `result_df` and then printing: print(result_df.head()).\n"
    )

    # Format only the base string (which contains the {style} token) to avoid
    # interfering with JSON braces in the rest of the prompt.
    base_filled = base.format(style=style)
    prompt = (
        f"{base_filled}\n"
        f"--- DATASET SCHEMA (context) ---\n{schema_snippet}\n\n"
        f"--- ANALYSIS TO REPRODUCE ---\n{analysis_context}\n\n"
        "Return a single fenced Python code block."
    )

    try:
        resp = model.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": 4096,
                "temperature": 0.1,
            },
        )
        text = _safe_response_text(resp)
        code = _extract_any_python_block(text)
        return code or "# No code generated."
    except Exception:
        return "# An error occurred while generating the code."


# ---------------------------------------------------------------------------
# JSON Extraction + Classifiers + Reconstruction
# ---------------------------------------------------------------------------

def _extract_json_block(text: str) -> str | None:
    """Extract a JSON object from model text output.

    Prefers a fenced ```json block. Falls back to the first {...} block.
    Returns the JSON string or None if not found.
    """
    if not isinstance(text, str) or not text:
        return None
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if m:
        return m.group(1)
    # Fallback: greedy outermost braces (best-effort)
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return m.group(0)
    return None


def classify_intent(
    question: str,
    schema_snippet: str,
    sample_rows: list[dict],
    tool_spec: list[dict],
    hinting: str | None = None,
) -> dict:
    """Classify user intent using Gemini native function-calling.

    Returns: {"intent": str, "params": dict, "confidence": float}
    On failure, returns UNKNOWN with confidence 0.0.
    """
    # Build tools in Gemini format (function_declarations)
    function_declarations = []
    for t in tool_spec or []:
        fn = {
            "name": t.get("name"),
            "description": t.get("description", ""),
            "parameters": t.get("parameters", {"type": "object"}),
        }
        if fn["name"]:
            function_declarations.append(fn)
    tools_payload = [{"function_declarations": function_declarations}] if function_declarations else None

    # Instantiate a model with tools
    model_with_tools = genai.GenerativeModel(_MODEL_NAME, tools=tools_payload)

    sample_preview = sample_rows[: min(len(sample_rows), 3)]
    hint_block = (hinting or "").strip()

    prompt = (
        "Determine which analysis function best answers the question using the schema.\n"
        "If no tool applies, do not call any function.\n\n"
        f"SCHEMA (truncated):\n{schema_snippet}\n\n"
        f"SAMPLE ROWS (truncated):\n{sample_preview}\n\n"
        f"HINTS:\n{hint_block}\n\n"
        f"QUESTION:\n{question}\n"
    )

    try:
        resp = model_with_tools.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": 2048,
                "temperature": 0.1,
            },
            tool_config={"function_calling_config": "ANY"},
        )
        # Find first function_call
        if getattr(resp, "candidates", None):
            for c in resp.candidates:
                content = getattr(c, "content", None)
                parts = getattr(content, "parts", None) if content else None
                if not parts:
                    continue
                for p in parts:
                    fc = getattr(p, "function_call", None)
                    if fc and getattr(fc, "name", None):
                        name = str(fc.name)
                        # args may be a dict-like
                        try:
                            args = dict(getattr(fc, "args", {}) or {})
                        except Exception:
                            args = {}
                        return {"intent": name, "params": args, "confidence": 0.95}
        # If no function call, return UNKNOWN
        return {"intent": "UNKNOWN", "params": {}, "confidence": 0.0}
    except Exception:
        return {"intent": "UNKNOWN", "params": {}, "confidence": 0.0}


def is_show_code_request(question: str) -> dict:
    """Detect if the user is asking to show the code.

    Returns {"is_code_request": bool}.
    """
    model = _ensure_model()
    prompt = (
        "Return STRICT JSON only indicating whether the user asks to show code.\n"
        "Schema: {\"is_code_request\": true|false}\n\n"
        f"USER: \"{question}\"\n"
        "Answer with only a JSON object."
    )
    try:
        resp = model.generate_content(prompt, generation_config={"max_output_tokens": 256, "temperature": 0.0})
        text = _safe_response_text(resp)
        js = _extract_json_block(text)
        if not js:
            return {"is_code_request": False}
        data = json.loads(js)
        return {"is_code_request": bool(data.get("is_code_request") is True)}
    except Exception:
        return {"is_code_request": False}


def reconstruct_code_from_tool_call(tool_name: str, params: dict, schema_snippet: str) -> str:
    """Provide a transparent Python implementation of the selected tool call.

    This is shown to users for transparency; it does not need to be executed.
    """
    tool = tool_name.upper().strip()
    code_lines: list[str] = [
        "import pandas as pd",
        "import numpy as np",
        "",
        "def run(df: pd.DataFrame, ctx: dict) -> dict:",
        "    row_limit = int((ctx or {}).get('row_limit', 200))",
    ]
    if tool == "AGGREGATE":
        dim = params.get("dimension", "<dimension>")
        metric = params.get("metric", "<metric>")
        func = params.get("func", "sum")
        code_lines += [
            f"    metric = pd.to_numeric(df['{metric}'], errors='coerce')",
            f"    grouped = df.groupby('{dim}', dropna=False).agg({{'{metric}': '{func}'}}).reset_index()",
            f"    grouped.columns = ['{dim}', '{metric}_{func}']",
            "    table = grouped.sort_values(by=grouped.columns[1], ascending=False).head(row_limit)",
        ]
    elif tool == "VARIANCE":
        dim = params.get("dimension", "<dimension>")
        a = params.get("periodA", "<periodA>")
        b = params.get("periodB", "<periodB>")
        code_lines += [
            f"    a = pd.to_numeric(df['{a}'], errors='coerce')",
            f"    b = pd.to_numeric(df['{b}'], errors='coerce')",
            f"    grouped = df.groupby('{dim}', dropna=False).agg({{'{a}': 'sum', '{b}': 'sum'}}).reset_index()",
            "    grouped['delta'] = grouped[b] - grouped[a]",
            "    with np.errstate(divide='ignore', invalid='ignore'):\n        grouped['pct_change'] = (grouped['delta'] / grouped[a]) * 100.0",
            "    table = grouped.sort_values(by='delta', ascending=False).head(row_limit)",
        ]
    elif tool == "FILTER_SORT":
        sort_col = params.get("sort_col", "<sort_col>")
        ascending = bool(params.get("ascending", False))
        limit = int(params.get("limit", 50))
        fcol = params.get("filter_col")
        fval = params.get("filter_val")
        code_lines += [
            "    dff = df",
        ]
        if fcol and fval is not None:
            code_lines += [
                f"    dff = dff[dff['{fcol}'].astype(str) == str({repr(fval)})]",
            ]
        code_lines += [
            f"    table = dff.sort_values(by='{sort_col}', ascending={ascending}).head({limit})",
        ]
    else:  # DESCRIBE or UNKNOWN
        code_lines += [
            "    table = df.select_dtypes(include=['number']).describe().reset_index().to_dict(orient='records')",
            "    return {'table': table, 'metrics': {'rows': len(df), 'columns': len(df.columns)}, 'chartData': {}}",
        ]
        return "\n".join(code_lines)

    code_lines += [
        "    return {",
        "        'table': table.to_dict(orient='records'),",
        "        'metrics': {'rows': len(df), 'columns': len(df.columns)},",
        "        'chartData': {}",
        "    }",
    ]
    return "\n".join(code_lines)


def format_final_response(question: str, result_df: pd.DataFrame) -> dict:
    """Create a compact summary and visuals stub for a fast-path result."""
    try:
        table_head = result_df.head(5).to_dict(orient="records")
    except Exception:
        table_head = []
    metrics = {"rows": int(getattr(result_df, "shape", [0, 0])[0] or 0),
               "columns": int(getattr(result_df, "shape", [0, 0])[1] or 0)}
    summary = generate_summary(question, table_head, metrics)
    visuals: list[dict] = []
    return {"summary": summary, "visuals": visuals}


def reconstruct_presentational_code(
    question: str,
    schema_snippet: str,
    sample_rows: list[dict] | None,
    last_exec_code: str | None = None,
) -> str:
    """Generate a clean presentational Python script for display.

    Uses the last executed fallback code (if provided) as context to align logic,
    but returns a simplified, commented script suitable for UI display only.
    """
    model = _ensure_model()
    preview = (sample_rows or [])[: min(len(sample_rows or []), 5)]
    context = last_exec_code or ""
    prompt = (
        "You are a senior data analyst. Create a clean, commented Python function\n"
        "`def run(df, ctx):` that reproduces the last analysis over the dataset schema below.\n"
        "Use idiomatic pandas/numpy and return a dict with keys: 'table' (list of rows),\n"
        "'metrics' (dict), and 'chartData' (object). Respect ctx.get('row_limit', 200).\n"
        "Avoid complex dtypes and keep it readable.\n\n"
        f"SCHEMA:\n{schema_snippet}\n\n"
        f"SAMPLE ROWS (truncated):\n{preview}\n\n"
        "If helpful, align with the following reference code (do not copy blindly; clean it up):\n"
        f"```python\n{context}\n```\n\n"
        "Return only one fenced Python block."
    )
    try:
        resp = model.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": _MAX_TOKENS,
                "temperature": 0.1,
            },
        )
        text = _safe_response_text(resp)
        code = _extract_code_block(text)
        return code or ""
    except Exception:
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

