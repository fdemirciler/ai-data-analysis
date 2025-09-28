from __future__ import annotations

import os
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

    RESULT must be a dict with keys: table (list[dict]), metrics (dict), chartData (dict), message (str optional).
    Allowed imports: pandas as pd, numpy as np, math, json. No file/network/system access. No writes.
    Keep output rows <= row_limit.
    """
    model = _ensure_model()
    sample_preview = sample_rows[: min(len(sample_rows), 10)]
    prompt = (
        "You are a Python data analysis assistant. Given a Pandas DataFrame df, "
        "write safe, concise code to answer the user's question.\n\n"
        "Requirements:\n"
        "- Define: def run(df, ctx):\n"
        "- Use only: pandas as pd, numpy as np, math, json.\n"
        "- NO file IO, NO network calls, NO system/process operations.\n"
        "- Return a dict RESULT with keys: 'table' (list of row dicts), 'metrics' (dict), 'chartData' (dict), 'message' (optional string).\n"
        f"- Limit table rows to <= {row_limit}.\n"
        "- 'chartData' must be a minimal object with: kind (e.g., 'bar'|'line'|'pie'), labels (list[str]), "
        "  and series (list of {label, data}).\n\n"
        f"Schema:\n{schema_snippet}\n\n"
        f"Sample rows (truncated):\n{sample_preview}\n\n"
        f"User question: {question}\n\n"
        "Return only Python code fenced in triple backticks."
    )
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
    model = _ensure_model()
    preview = table_head[: min(len(table_head), 5)]
    prompt = (
        "Summarize the analysis results in one short paragraph followed by up to 3 concise bullets.\n"
        "Be factual and avoid repetition.\n\n"
        f"Question: {question}\n"
        f"Table sample: {preview}\n"
        f"Metrics: {metrics}\n"
    )
    resp = model.generate_content(prompt, generation_config={"max_output_tokens": 256, "temperature": 0.2})
    text = ""
    try:
        text = resp.text or ""
    except Exception:
        # Fallback when response is blocked/empty
        text = ""
    return (text or "Analysis complete. See chart and table for details.").strip()


def _extract_code_block(text: str) -> str:
    import re

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
