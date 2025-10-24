from __future__ import annotations

import os
import re
import json
from typing import Any, Dict, List

import pandas as pd
import google.generativeai as genai
import config

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MODEL_NAME = config.GEMINI_MODEL_NAME
_API_KEY = config.GEMINI_API_KEY

_MAX_TOKENS = config.GEMINI_MAX_TOKENS
_TEMPERATURE = config.GEMINI_TEMPERATURE

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
        generation_config=config.GEMINI_GENERATION_CONFIG,
    )

    text = _safe_response_text(resp)
    code = _extract_code_block(text)
    if not code or not re.search(r"def\s+run\s*\(", code):
        alt = _extract_any_python_block(text)
        if alt:
            return _wrap_into_run_if_needed(alt)
        raise RuntimeError("CODEGEN_FAILED: Missing valid 'def run(df, ctx):' implementation.")
    return code


# ---------------------------------------------------------------------------
# Generate Short Chat Title
# ---------------------------------------------------------------------------

def _sanitize_title(raw: str, max_len: int = 60) -> str:
    """Sanitize and normalize a model-produced title to sentence case.

    Rules applied here regardless of model output:
    - Remove surrounding quotes/backticks and emojis/symbols (keep ()-:/& and dots in numbers)
    - Collapse whitespace
    - Lowercase everything, then capitalize first letter only (sentence case)
    - Normalize ' vs ' to lowercase 'vs'
    - Strip trailing punctuation (.,;:!?)
    - Truncate to max_len
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    # Strip surrounding quotes/backticks
    if (s.startswith("\"") and s.endswith("\"")) or (s.startswith("'") and s.endswith("'")) or (s.startswith("`") and s.endswith("`")):
        s = s[1:-1].strip()
    # Remove most emojis/symbols by keeping a conservative set
    s = re.sub(r"[^\w\s()\-:./&]", "", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    # Lowercase baseline
    s = s.lower()
    # Normalize ' vs '
    s = re.sub(r"\bvs\b", "vs", s, flags=re.IGNORECASE)
    # Strip trailing punctuation
    s = re.sub(r"[\.;:!?]+$", "", s).strip()
    # Sentence case: first letter uppercase only
    s = s[0].upper() + s[1:] if s else s
    # Length cap
    if len(s) > max_len:
        s = s[: max_len].rstrip()
    return s


def generate_title(question: str, summary: str) -> str:
    """Generate a concise chat title based on the first exchange.

    Hard constraints (prompted and sanitized):
    - 3–6 words, sentence case, no quotes/emojis
    - No trailing period
    - Use 'vs' lowercase when appropriate
    - ≤ 60 characters, may use parentheses
    """
    model = _ensure_model()
    q = (question or "").strip()
    s = (summary or "").strip()

    prompt = (
        "You generate short chat titles.\n"
        "Produce a concise 3–6 word title that is meaningful and grammatically correct, in sentence case.\n"
        "Rules: no quotes, no emojis, no trailing punctuation, avoid pronouns like 'me/my', avoid leading articles unless needed, ≤ 60 characters.\n"
        "If a comparison is present, use the form 'a vs b' with lowercase 'vs'. Parentheses are allowed.\n\n"
        f"User Question:\n{q}\n\n"
        f"Assistant Summary:\n{s}\n\n"
        "Return ONLY the title text with no extra commentary."
    )

    try:
        resp = model.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": 24,
                "temperature": 0.25,
            },
        )
        text = _safe_response_text(resp)
        title = _sanitize_title(text)
        # Guardrails: prefer 3–6 words
        words = [w for w in title.split(" ") if w]
        if 3 <= len(words) <= 8 and title:
            return title
        # If outside range but non-empty, still return sanitized title (length already capped)
        if title:
            return title
    except Exception:
        pass

    # Fallback: minimal heuristic from question
    if q:
        # Try to transform "compare X and Y" → "x vs y" (lowercase vs)
        m = re.search(r"compare\s+(.+?)\s+and\s+(.+)$", q, flags=re.IGNORECASE)
        if m:
            rough = f"{m.group(1).strip()} vs {m.group(2).strip()}"
        else:
            rough = q
        # Remove leading polite phrases and pronouns
        rough = re.sub(r"^(please|can you|could you|would you|show|give me|tell me|me|my)\b[:,]?\s*", "", rough, flags=re.IGNORECASE)
        return _sanitize_title(rough)
    return ""


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
        "Organize your interpretation into multiple short paragraphs for readability. "
        "Start a new paragraph whenever the focus or comparison changes (e.g., contrasts, trends, anomalies, conclusions)."
    )

    try:
        resp = model.generate_content(
            prompt,
            generation_config=config.PRESENTATIONAL_GENERATION_CONFIG,
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
    fused = config.GEMINI_FUSED
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
        generation_config=config.GEMINI_GENERATION_CONFIG,
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
            generation_config=config.GEMINI_GENERATION_CONFIG,
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
        generation_config=config.GEMINI_GENERATION_CONFIG,
    )
    text = _safe_response_text(resp)
    code = _extract_code_block(text)
    if not code or not re.search(r"def\s+run\s*\(", code):
        alt = _extract_any_python_block(text)
        if alt:
            return _wrap_into_run_if_needed(alt)
        # As last resort, wrap the raw text
        if text:
            return _wrap_into_run_if_needed(text)
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


def _wrap_into_run_if_needed(code: str) -> str:
    """Ensure returned code defines def run(df, ctx). If not, wrap the snippet."""
    if isinstance(code, str) and re.search(r"def\s+run\s*\(", code):
        return code
    snippet = (code or "").strip()
    indent = "    "
    body = "\n".join(indent + line for line in snippet.splitlines()) if snippet else f"{indent}result_df = df"
    wrapped = (
        "def run(df, ctx):\n"
        f"{indent}row_limit = int((ctx or {{}}).get('row_limit', 200))\n"
        f"{body}\n"
        f"{indent}try:\n"
        f"{indent*2}result_df\n"
        f"{indent}except NameError:\n"
        f"{indent*2}result_df = df\n"
        f"{indent}table = result_df.head(row_limit)\n"
        f"{indent}return {{'table': table.to_dict(orient='records'), 'metrics': {{'rows': len(df), 'columns': len(df.columns)}}, 'chartData': {{}}}}\n"
    )
    return wrapped


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
            generation_config=config.PRESENTATIONAL_GENERATION_CONFIG,
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
    # Ensure client configured (API key) even if other functions haven't been called yet
    try:
        _ensure_model()
    except Exception:
        pass

    # Build tools in Gemini format (function_declarations) with Gemini Schema casing
    def _to_gemini_schema(js: dict | None) -> dict:
        if not isinstance(js, dict):
            return {"type": "OBJECT"}
        t = str(js.get("type", "object")).lower()
        type_map = {
            "object": "OBJECT",
            "string": "STRING",
            "number": "NUMBER",
            "integer": "INTEGER",
            "boolean": "BOOLEAN",
            "array": "ARRAY",
        }
        out: dict = {"type": type_map.get(t, "OBJECT")}
        # properties
        if "properties" in js and isinstance(js.get("properties"), dict):
            out["properties"] = {k: _to_gemini_schema(v) for k, v in js["properties"].items()}
        # items for arrays
        if "items" in js:
            out["items"] = _to_gemini_schema(js.get("items"))
        # enum
        if "enum" in js:
            out["enum"] = list(js.get("enum") or [])
        # required
        if "required" in js:
            out["required"] = list(js.get("required") or [])
        # minimum/maximum/default passthrough (non-breaking)
        for k in ("minimum", "maximum", "default", "description"):
            if k in js:
                out[k] = js[k]
        return out

    function_declarations = []
    for t in tool_spec or []:
        name = t.get("name")
        if not name:
            continue
        params_js = t.get("parameters", {"type": "object"})
        fn = {
            "name": name,
            "description": t.get("description", ""),
            "parameters": _to_gemini_schema(params_js),
        }
        # Append examples if present
        examples = t.get("examples")
        if examples and isinstance(examples, list):
            fn["description"] += f"\n\nExample queries: {', '.join(examples[:5])}"
        function_declarations.append(fn)
    tools_payload = [{"function_declarations": function_declarations}] if function_declarations else None

    def _build_model_with_tools(model_name: str):
        """Instantiate a GenerativeModel with tools using types when available."""
        # Preferred: typed Tool(FunctionDeclaration(Schema))
        try:
            types = getattr(genai, "types", None)
            Tool = getattr(types, "Tool", None)
            FunctionDeclaration = getattr(types, "FunctionDeclaration", None)
            Schema = getattr(types, "Schema", None)
            if Tool and FunctionDeclaration and Schema and function_declarations:
                fns = []
                for fd in function_declarations:
                    fns.append(FunctionDeclaration(
                        name=fd.get("name"),
                        description=fd.get("description", ""),
                        parameters=Schema(**fd.get("parameters", {"type": "OBJECT"}))
                    ))
                tool_obj = Tool(function_declarations=fns)
                return genai.GenerativeModel(model_name, tools=[tool_obj])
        except Exception:
            pass
        # Fallback: dict tools
        return genai.GenerativeModel(model_name, tools=tools_payload)

    sample_preview = sample_rows[: min(len(sample_rows), 3)]
    hint_block = (hinting or "").strip()

    prompt = (
        "You are a data analysis router. Determine if ONE tool call can answer the user's question.\n\n"
        "WHEN TO CALL A TOOL:\n"
        "- Question clearly matches a tool's purpose → Call it\n"
        "- Minor column name variations (case, spacing) → Call anyway, use closest match\n"
        "- Simple aggregations, filters, summaries → Call the appropriate tool\n\n"
        "WHEN NOT TO CALL:\n"
        "- AGGREGATE tool but user wants multiple metrics in one grouped table → Don't call\n"
        "- Request needs multiple sequential operations (filter THEN sort THEN pivot) → Don't call\n"
        "- Essential columns genuinely missing from schema → Don't call\n\n"
        f"SCHEMA (truncated):\n{schema_snippet}\n\n"
        f"SAMPLE ROWS (truncated):\n{sample_preview}\n\n"
        f"HINTS:\n{hint_block}\n\n"
        f"QUESTION:\n{question}\n"
    )

    def _try_once(model_name: str) -> dict | None:
        try:
            mdl = _build_model_with_tools(model_name)
            # Try new-style tool_config first
            try:
                resp = mdl.generate_content(
                    prompt,
                    generation_config={
                        "max_output_tokens": config.GEMINI_MAX_TOKENS,
                        "temperature": config.CLASSIFIER_TEMPERATURE,
                    },
                    tool_config={"function_calling_config": {"mode": "ANY"}},
                )
            except Exception:
                # Fallback to older style
                resp = mdl.generate_content(
                    prompt,
                    generation_config={
                        "max_output_tokens": config.GEMINI_MAX_TOKENS,
                        "temperature": config.CLASSIFIER_TEMPERATURE,
                    },
                    tool_config={"function_calling_config": "ANY"},
                )
            if getattr(resp, "candidates", None):
                for c in resp.candidates:
                    content = getattr(c, "content", None)
                    parts = getattr(content, "parts", None) if content else None
                    if not parts:
                        continue
                    for p in parts:
                        fc = getattr(p, "function_call", None) or getattr(p, "functionCall", None)
                        if fc and getattr(fc, "name", None):
                            name = str(fc.name)
                            try:
                                args = dict(getattr(fc, "args", {}) or {})
                            except Exception:
                                args = {}
                            return {"intent": name, "params": args, "confidence": 0.95}
            return None
        except Exception:
            return None

    tried = set()
    candidates = [_MODEL_NAME]
    override = config.CLASSIFIER_MODEL_OVERRIDE
    if override:
        candidates.append(override)
    # Known-good for tool calls
    candidates.append("gemini-1.5-flash")
    for mn in candidates:
        if not mn or mn in tried:
            continue
        tried.add(mn)
        out = _try_once(mn)
        if out:
            return out
    # Heuristic fallback: simple parser for common single-step asks
    try:
        q = (question or "").strip()
        ql = q.lower()
        cols: list[str] = []
        try:
            h = json.loads(hinting or "{}") if isinstance(hinting, str) else (hinting or {})
            if isinstance(h, dict) and isinstance(h.get("columns"), list):
                cols = [str(c) for c in h.get("columns")]
        except Exception:
            cols = []

        def best_col(token: str) -> str | None:
            if not token:
                return None
            tl = token.strip().lower()
            if not tl:
                return None
            for c in cols:
                if c.lower() == tl:
                    return c
            for c in cols:
                if tl in c.lower():
                    return c
            return None

        # sum/total pattern with optional "by <dim>"
        m = re.search(r"\b(sum|total)\s+of\s+([\w\s\-]+?)(?:\s+column)?(?:\s+by\s+([\w\s\-]+))?\b", ql)
        if not m:
            m = re.search(r"\b(sum|total)\s+([\w\s\-]+?)(?:\s+column)?(?:\s+by\s+([\w\s\-]+))?\b", ql)
        if m:
            metric_tok = m.group(2).strip()
            dim_tok = (m.group(3) or "").strip()
            metric_col = best_col(metric_tok)
            dim_col = best_col(dim_tok) if dim_tok else None
            if metric_col and dim_col:
                return {"intent": "run_aggregation", "params": {"dimension": dim_col, "metric": metric_col, "func": "sum"}, "confidence": 0.7}
            if metric_col:
                return {"intent": "sum_column", "params": {"column": metric_col}, "confidence": 0.7}
    except Exception:
        pass

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
        resp = model.generate_content(prompt, generation_config=config.GEMINI_GENERATION_CONFIG)
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
        a = params.get("period_a", "<period_a>")
        b = params.get("period_b", "<period_b>")
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
            generation_config=config.PRESENTATIONAL_GENERATION_CONFIG,
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
