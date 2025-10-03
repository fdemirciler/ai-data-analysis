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
    """Ask Gemini to produce Python code implementing def run(df, ctx): -> RESULT."""
    model = _ensure_model()
    sample_preview = sample_rows[: min(len(sample_rows), 10)]
    
    # --- PROMPT ENHANCEMENT ---
    # This prompt is now much more specific to prevent syntax errors and improve formatting.
    prompt = (
        "You are an expert Python data analyst. Your task is to write a single, syntactically correct Python function `run(df, ctx)` "
        "that performs a data analysis based on the user's question. "
        "You will be given the schema and sample rows of a pandas DataFrame `df`.\n\n"
        "RULES:\n"
        "1. Your ENTIRE output must be a single Python code block starting with ```python and ending with ```.\n"
        "2. DO NOT include any text, explanations, or markdown before or after the code block.\n"
        "3. The function signature MUST be `def run(df, ctx):`.\n"
        "4. The function MUST return a dictionary with keys: 'table' (list of dicts), 'metrics' (dict), and 'chartData' (dict).\n"
        "5. Round all floating-point numbers in the output to a maximum of 3 decimal places.\n"
        "6. Handle division by zero or invalid calculations gracefully. The final JSON output cannot contain NaN, Infinity, or -Infinity. Replace these with None.\n"
        "7. Allowed imports are: pandas as pd, numpy as np, math, json.\n"
        "8. Only generate a chart if the user's question explicitly asks for a 'chart', 'plot', 'graph', or 'visualization'. Otherwise, return an empty dictionary for 'chartData', like so: {'kind': 'bar', 'labels': [], 'series': []}.\n\n"
        f"SCHEMA:\n{schema_snippet}\n\n"
        f"SAMPLE ROWS:\n{sample_preview}\n\n"
        f"USER QUESTION: \"{question}\"\n\n"
        "CODE:"
    )
    # --- END PROMPT ENHANCEMENT ---

    resp = model.generate_content(
        prompt,
        generation_config={"max_output_tokens": 512, "temperature": 0.2},
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
    if not code:
        # Safe fallback: generic preview code
        code = (
            "import pandas as pd\n"
            "import numpy as np\n"
            "import math\n"
            "def run(df, ctx):\n"
            "    try:\n"
            "        row_limit = int(ctx.get('row_limit', 200))\n"
            "    except Exception:\n"
            "        row_limit = 200\n"
            "    table = df.head(row_limit).to_dict(orient='records')\n"
            "    metrics = {'rows': int(len(df))}\n"
            "    chart = {'kind': 'bar', 'labels': [], 'series': [{'label': 'Count', 'data': []}]}\n"
            "    obj_cols = [c for c in df.columns if df[c].dtype == 'object']\n"
            "    if obj_cols:\n"
            "        vc = df[obj_cols[0]].astype('string').value_counts().head(5)\n"
            "        chart['labels'] = [str(x) for x in vc.index.tolist()]\n"
            "        chart['series'][0]['data'] = [int(x) for x in vc.values.tolist()]\n"
            "    else:\n"
            "        num_cols = df.select_dtypes(include=['number']).columns.tolist()\n"
            "        if num_cols:\n"
            "            s = df[num_cols[0]].dropna().head(5)\n"
            "            chart['labels'] = [str(i) for i in range(len(s))]\n"
            "            chart['series'][0]['data'] = [float(x) for x in s.tolist()]\n"
            "    return {'table': table, 'metrics': metrics, 'chartData': chart}\n"
        )
    return code


def generate_summary(question: str, table_head: list[dict], metrics: dict) -> str:
    """Generates a data-driven summary by interpreting the analysis results."""
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
        "YOUR INTERPRETATION:"
    )
    # --- END PROMPT ENHANCEMENT ---

    resp = model.generate_content(prompt, generation_config={"max_output_tokens": 256, "temperature": 0.3})
    text = ""
    try:
        text = resp.text or ""
    except Exception:
        # Fallback when response is blocked/empty
        text = ""
    return (text or "Analysis complete. See chart and table for details.").strip()


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
    
    # This prompt is stricter about the output format and includes formatting rules.
    prompt = (
        "You are an expert Python data analyst. Produce both the code and a short summary in a structured output.\n\n"
        "RULES FOR THE CODE BLOCK:\n"
        "1. The function signature MUST be `def run(df, ctx):`.\n"
        "2. The function MUST return a dictionary with keys: 'table', 'metrics', and 'chartData'.\n"
        "3. Round all floating-point numbers in the output to a maximum of 3 decimal places.\n"
        "4. Handle division by zero or invalid calculations gracefully. The final JSON output cannot contain NaN, Infinity, or -Infinity. Replace these with None.\n"
        "5. Allowed imports are: pandas as pd, numpy as np, math, json.\n"
        "6. Only generate a chart if the user's question explicitly asks for a 'chart', 'plot', 'graph', or 'visualization'. Otherwise, return an empty dictionary for 'chartData', like so: {'kind': 'bar', 'labels': [], 'series': []}.\n\n"
        "RULES FOR THE SUMMARY (This is a pre-analysis plan):\n"
        "1. Provide a one-paragraph summary of the analysis that the code will perform.\n\n"
        "OUTPUT FORMAT (MUST BE EXACTLY THIS):\n"
        "[CODE_START]\n"
        "```python\n"
        "# your python code here\n"
        "```\n"
        "[CODE_END][SUMMARY_START]\n"
        "Your short plan summary here.\n"
        "[SUMMARY_END]\n\n"
        "--- START OF DATA ---\n"
        f"Schema:\n{schema_snippet}\n\n"
        f"Sample rows:\n{sample_preview}\n\n"
        f"User question: {question}\n"
    )
    
    resp = model.generate_content(
        prompt,
        generation_config={"max_output_tokens": 768, "temperature": 0.2},
    )
    text = ""
    try:
        text = resp.text or ""
    except Exception:
        text = ""

    # Parse structured markers first
    code = ""
    summary = ""
    try:
        m_code_block = re.search(r"\[CODE_START\](.*?)\[CODE_END\]", text, flags=re.DOTALL | re.IGNORECASE)
        if m_code_block:
            code_section = m_code_block.group(1)
            code = _extract_code_block(code_section)
        else:
            code = _extract_code_block(text)

        m_sum = re.search(r"\[SUMMARY_START\](.*?)\[SUMMARY_END\]", text, flags=re.DOTALL | re.IGNORECASE)
        if m_sum:
            summary = m_sum.group(1).strip()
        else:
            summary = (text.strip().split("\n\n")[-1] or "").strip()
    except Exception:
        # Fallback to two-call path if parsing failed badly
        code = _extract_code_block(text)
        if not code:
            code = generate_analysis_code(question, schema_snippet, sample_rows, row_limit=row_limit)
        summary = "Analysis planned. Executed results will follow."

    if not code:
        code = generate_analysis_code(question, schema_snippet, sample_rows, row_limit=row_limit)
    if not summary:
        summary = "Analysis planned. Executed results will follow."
    return code, summary

