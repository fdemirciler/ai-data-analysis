*** Suggested Plan 1 ***

# Hybrid Dispatcher Classifier Reliability Upgrade — Implementation Plan

This document defines a detailed, production-ready plan to fix the low-confidence classifier issue and improve the reliability, accuracy, and maintainability of the hybrid dispatcher architecture.

---

## 1. Problem Summary

### 1.1 Root Cause
The current `classify_intent()` implementation provides insufficient prompt context and relies on textual JSON parsing instead of Gemini’s **native function-calling** mechanism.  
As a result:
- The model returns low confidence or UNKNOWN intents.
- All queries route to the fallback path.
- Confidence thresholds never trigger the fast path.

---

## 2. Goals

- Transition the classifier to **Gemini native function-calling**.
- Increase classification accuracy and confidence.
- Preserve backward compatibility and telemetry.
- Simplify maintenance and improve observability.

---

## 3. Implementation Plan

### 3.1 Files Affected
- `backend/functions/orchestrator/analysis_toolkit.py`
- `backend/functions/orchestrator/gemini_client.py`
- `backend/functions/orchestrator/main.py`
- `backend/deploy-analysis.ps1`

---

## 4. Changes by Problem Area

### 🧭 Problem 1 — Low Confidence and Universal Fallback

#### Problem
`classify_intent()` uses plain-text prompts and JSON parsing, resulting in low-confidence or UNKNOWN outputs.

#### Fix
Use Gemini’s **native function-calling mode** with rich tool specifications.

#### Code Changes

**File:** `backend/functions/orchestrator/analysis_toolkit.py`

```python
# New Gemini-compatible TOOLS_SPEC for function calling

TOOLS_SPEC = [
    {
        "name": "run_aggregation",
        "description": "Performs a groupby aggregation (sum, average, count) on a numeric metric grouped by a dimension.",
        "parameters": {
            "type": "object",
            "properties": {
                "dimension": {"type": "string", "description": "Column to group by."},
                "metric": {"type": "string", "description": "Numeric column to aggregate."},
                "func": {"type": "string", "enum": ["sum", "average", "count"], "description": "Aggregation function."}
            },
            "required": ["dimension", "metric", "func"]
        }
    },
    {
        "name": "run_variance",
        "description": "Calculates difference and % change between two numeric period columns.",
        "parameters": {
            "type": "object",
            "properties": {
                "dimension": {"type": "string", "description": "Column that identifies the metric being compared."},
                "period_a": {"type": "string", "description": "First period column (earlier)."},
                "period_b": {"type": "string", "description": "Second period column (later)."}
            },
            "required": ["dimension", "period_a", "period_b"]
        }
    },
    {
        "name": "run_filter_and_sort",
        "description": "Filters (optional) and sorts a DataFrame, optionally limiting results.",
        "parameters": {
            "type": "object",
            "properties": {
                "sort_col": {"type": "string", "description": "Column to sort by."},
                "ascending": {"type": "boolean", "description": "True for ascending sort."},
                "limit": {"type": "integer", "description": "Number of rows to return."},
                "filter_col": {"type": "string", "description": "Optional column to filter on."},
                "filter_val": {"type": "string", "description": "Optional filter value."}
            },
            "required": ["sort_col", "ascending", "limit"]
        }
    },
    {
        "name": "run_describe",
        "description": "Summarizes numeric columns with count, mean, std, min, and max.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }
]
```

**File:** `backend/functions/orchestrator/gemini_client.py`

```python
def classify_intent(question: str, schema_snippet: str, tool_spec: list[dict]) -> dict:
    '''
    Classifies user intent using Gemini's native function-calling mode.
    Returns: {"intent": str, "params": dict, "confidence": float}
    '''
    model = _ensure_model()
    model_with_tools = genai.GenerativeModel(_MODEL_NAME, tools=tool_spec)

    prompt = (
        "Determine which analysis function best answers the question using the schema. "
        "If no tool applies, do not call any function.\n\n"
        f"SCHEMA:\n{schema_snippet}\n\n"
        f"QUESTION:\n{question}\n"
    )

    try:
        response = model_with_tools.generate_content(prompt, tool_config={'function_calling_config': "ANY"})
        function_call = response.candidates[0].content.parts[0].function_call
        if function_call:
            name = function_call.name
            params = dict(function_call.args.items())
            return {"intent": name.upper(), "params": params, "confidence": 0.95}
    except Exception as e:
        print(f"Function calling failed: {e}")
    return {"intent": "UNKNOWN", "params": {}, "confidence": 0.0}
```

#### Expected Outcome
- Classifier produces structured, high-confidence outputs.
- Most simple analytical queries route through fast path.
- No manual JSON parsing or repair attempts required.

---

### ⚙️ Problem 2 — Overly Strict Routing Logic

**File:** `backend/functions/orchestrator/main.py`

```python
soft_threshold = MIN_FASTPATH_CONFIDENCE - 0.15
params_ok = validate_params_against_schema(intent, params, column_names)

if intent in {"AGGREGATE","VARIANCE","FILTER_SORT","DESCRIBE"} and (
    confidence >= MIN_FASTPATH_CONFIDENCE or (params_ok and confidence >= soft_threshold)
):
    strategy = "fastpath"
else:
    strategy = "fallback"
```

#### Expected Outcome
- Increased fast-path adoption.
- More resilient to small confidence fluctuations.

---

### 💾 Problem 3 — Artifact Collision

**File:** `backend/functions/orchestrator/main.py`

```python
table_path = f"{results_prefix}/fallback_table.json"
metrics_path = f"{results_prefix}/fallback_metrics.json"
chart_path = f"{results_prefix}/fallback_chart_data.json"
```

#### Expected Outcome
- Prevents collisions between fallback and fast-path runs.

---

### 🧱 Problem 4 — Code Reconstruction Logic

**File:** `backend/functions/orchestrator/gemini_client.py`

```python
def reconstruct_code_from_tool_call(tool_name: str, params: dict, schema_snippet: str) -> str:
    model = _ensure_model()
    prompt = (
        f"A data analysis was performed using '{tool_name}' with parameters: {json.dumps(params)}.\n"
        f"The schema is:\n{schema_snippet}\n"
        "Write a clean, commented Python script using Pandas to replicate this analysis. "
        "Enclose it in a ```python block."
    )
    response = model.generate_content(prompt)
    return _extract_code_block(_safe_response_text(response))
```

#### Expected Outcome
- Simplified reconstruction logic.
- Cleaner, readable code output.

---

### ⚡ Problem 5 — Cold Start Latency

**File:** `backend/deploy-analysis.ps1`

```bash
gcloud functions deploy chat --memory=512Mi --min-instances=1 --set-env-vars=FASTPATH_ENABLED=1,FALLBACK_ENABLED=1
```

#### Expected Outcome
- Instant responsiveness, minimal latency.

---

### 🔍 Problem 6 — Observability

**File:** `backend/functions/orchestrator/main.py`

```python
if os.getenv("LOG_CLASSIFIER_RESPONSE") == "1":
    yield _sse_format({
        "type": "classification_result",
        "data": {"intent": intent, "params": params, "confidence": confidence}
    })
```

#### Expected Outcome
- Full visibility into routing and confidence distribution.

---

## 5. Rollout Plan

1. **Deploy to staging** with:
   ```bash
   CLASSIFIER_TIMEOUT_SECONDS=12
   MIN_FASTPATH_CONFIDENCE=0.55
   LOG_CLASSIFIER_RESPONSE=1
   ```
2. **Test queries**: "sum revenue by region", "compare 2023 and 2024", "show me the code".
3. **Validate**: 70–80% fast-path coverage, confidence ≥0.85.
4. **Tune** threshold to 0.65–0.7 post-stabilization.

---

## 6. Expected Global Outcomes

| Area                    | Before         | After       |
| ----------------------- | -------------- | ----------- |
| Classification accuracy | ~30%           | >90%        |
| Avg. LLM latency        | 5–8s           | 2–3s        |
| Fast-path routing rate  | <5%            | 70–80%      |
| Maintainability         | Template-based | Declarative |
| Cold start time         | 5–10s          | <1s         |

---

**End of Implementation Plan**


*** Suggested Plan 2 ***

Detailed Hybrid Implementation Guide
This document provides a step-by-step technical guide with code snippets to implement the approved "Hybrid Pipeline Implementation Plan (Final)". Each task is broken down into the problem, the specific code fix, and the expected outcome.

Task 1: Immediate Fixes & Diagnostics (The "Un-blocker")
The goal is to stop the "always fallback" behavior and gain visibility into the classifier's performance.

Problem
The classifier may be timing out or returning confidence scores just below the current threshold (0.65), causing all queries to take the fallback path. We lack the necessary logs to diagnose this.

Suggested Fix
1. Relax Timeouts and Thresholds

File: backend/deploy-analysis.ps1

Action: Modify the gcloud deploy command for the chat function to update the environment variables. This can also be done in env.chat.yaml.

# In deploy-analysis.ps1

# ... existing code ...
# Chat env (YAML)
@"
# ... other vars
MIN_FASTPATH_CONFIDENCE: "0.55" # Temporarily lower from 0.65
CLASSIFIER_TIMEOUT_SECONDS: "12" # Increase from 8
# ... other vars
"@ | Out-File -Encoding ascii -FilePath $CHAT_ENV_FILE
# ... existing code ...

2. Add Diagnostic Logging

File: backend/functions/orchestrator/main.py

Action: Add a structured log entry immediately after the classify_intent call within the _events generator.

# In main.py, inside the _events generator

# ... after fetching payload_obj
import logging

# --- Smart Dispatcher: Fast-path Classification ---
if FASTPATH_ENABLED and (FORCE_FALLBACK_MIN_ROWS <= 0 or dataset_rows < FORCE_FALLBACK_MIN_ROWS):
    # ... (hinting block)

    classification = None
    raw_text_from_llm = "" # Variable to hold raw response
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(
                gemini_client.classify_intent,the functiont    question, task
           schema_snippet,(                analysis_toolkit.TOOLS_SPEC,...) 
       )

             ... (timeout loop from your existing code)t
o retur classification = fut.result()
       n a dict that includes raw text
        raw_text_from_llm = classification.get("_raw_text", "")

    except Exception as e:
        classification = {"intent": "UNKNOWN", "params": {}, "confidence": 0.0}
        logging.error(f"Classifier failed: {e}")

    # ---> ADD THIS LOGGING BLOCK <---
    logging.info(json.dumps({
        "event": "classifier_result",
        "intent": classification.get("intent"),
        "params": classification.get("params"),
        "confidence": classification.get("confidence"),
        "raw_text_from_llm": raw_text_from_llm
    }))
    # ---> END LOGGING BLOCK <---

    intent = (classification or {}).get("intent") or "UNKNOWN"
    # ... rest of the dispatcher logic

Expected Outcome
The system will begin routing some simple queries to the fast path. Your Cloud Logging will now contain classifier_result entries, providing the critical data needed to tune the confidence threshold and classifier prompt.

Task 2: Implement Native Function Calling for the Classifier
This is the core architectural fix for classifier reliability.

Problem
The current classify_intent prompt is not using Gemini's native, optimized mode for tool selection, leading to low confidence and parsing fragility.

Suggested Fix
1. Upgrade Toolkit Specification

File: backend/functions/orchestrator/analysis_toolkit.py

Action: Replace the existing simple TOOLS_SPEC list with a detailed, JSON Schema-compliant specification.

# In analysis_toolkit.py

# ... (existing functions)

# Replace the old TOOLS_SPEC with this new, detailed version
TOOLS_SPEC = [
    {
        "name": "run_aggregation",
        "description": "Performs groupby aggregation (sum, average, count) on a numeric metric, grouped by a dimension.",
        "parameters": {
            "type": "object",
            "properties": {
                "dimension": {"type": "string", "description": "The column to group by (e.g., 'Region', 'Product')."},
                "metric": {"type": "string", "description": "The numeric column to aggregate (e.g., 'Sales', 'Profit')."},
                "func": {"type": "string", "description": "The aggregation function to apply. One of: 'sum', 'average', 'count', 'min', 'max'."}
            },
            "required": ["dimension", "metric", "func"]
        }
    },
    {
        "name": "run_variance",
        "description": "Calculates the difference and percentage change between two numeric period columns, grouped by a dimension.",
        "parameters": {
            "type": "object",
            "properties": {
                "dimension": {"type": "string", "description": "The column that identifies the items being compared (e.g., 'Metric Name')."},
                "period_a": {"type": "string", "description": "The column for the first (typically earlier) period (e.g., '2023')."},
                "period_b": {"type": "string", "description": "The column for the second (typically later) period (e.g., '2024')."}
            },
            "required": ["dimension", "period_a", "period_b"]
        }
    },
    {
        "name": "run_filter_and_sort",
        "description": "Optionally filters a dataset by a specific value in a column, then sorts the result and returns the top N rows.",
        "parameters": {
            "type": "object",
            "properties": {
                "sort_col": {"type": "string", "description": "The column to sort the final result by."},
                "ascending": {"type": "boolean", "description": "Set to true for ascending order, false for descending."},
                "limit": {"type": "integer", "description": "The number of rows to return (e.g., for 'top 5', limit is 5)."},
                "filter_col": {"type": "string", "description": "(Optional) The column to apply a filter on."},
                "filter_val": {"type": "string", "description": "(Optional) The value to filter for in the filter_col."}
            },
            "required": ["sort_col", "ascending", "limit"]
        }
    },
    {
        "name": "run_describe",
        "description": "Provides a basic statistical summary of the dataset's numeric columns (count, mean, std, min, max, etc.).",
        "parameters": {"type": "object", "properties": {}}
    }
]

2. Refactor classify_intent Function

File: backend/functions/orchestrator/gemini_client.py

Action: Replace the entire classi below.h uses the native funct
import logging # Add this import at the top of the fileion-calling API.

# In gemini_client.py

def classify_intent(
    question: str,
    schema_sre less critical with this new approach
) -> dict:
    """
    Classifies user intent using Gemini's native function-calling mode.
    Returns a dict like {"inte float, "_raw_text": str}., "params": dict, "confidence": float}.
    """
    try:
 tance configured with the tools
        model_with_tools = genai.GenerativeModel(
            _MODEL_NAME,
            tools=tool_spec 
        )

        prompt = (
            "Analyze the user's question and the provided data schema to determine "
            "which tool, if any, should be called to answer the question. If no tool is "
            "appropriate, do not call any function.\n\n"
            f"SCHEMA:\n{schema_snippet}\n\n"
            f"USER QUESTImodel decide which tool to call
        response = model_with_tools.generate_content(
            prompt,
            tool_config={'function_calling_config': "ANY"}
        )

        response_part = response.candidates[0].content.parts[0]

        if hasattr(response_part, 'function_call') and response_part.function_call:
            function_call = response_part.function_call
            toopb2.Struct to a Python dict
            params = {key: value for key, value in fgn a high confidence score.
            return {"intent": tool_name.upper(), "params": params, "confidence": 0.95, "_raw_text": str(response AttributeError, Exception)ValueError, IndexError, AttributeError) as e:
        logging.error(f"Function calling failed, fallirror occurred, fall back to UNKNOWN
    return {"intent": "UNKNOWN", "params": {}, "confidence": 0.0, "_raw_text": "No unction call was made by the model."}


Expected Outcome
The cl accurate, making the confidenceate. The reported conctive. The need for a "soft-accept" logic will be reduced, but we will still implement it as a valuable safety net.

Task 3: Implement "Soft-Ac routing.
Problem
The router might reject a classification with medium confidence even if the parameters are perfectly valid and usable.lity of the LLM's output before making a routing decision.

Problem
Even with native function calling, the model might occasionally hallucinate a column name or have slightly lower confidence. The router should be smart enough to accept a usable tool call, even with medium confidence.

Suggested Fix
1. Create a Parameter Validator Helper

File: backend/functions/orchestrator/main.py

Action: Add a new helper function within main.py to validate the parameters returned by the classifier.

# In main.py

def validate_params(intent: str, params: dict, column_names: list) -> bool:
    """
    Validates that the parameters for a given intent map to real columns,
    resolving aliases where possible. Returns True if valid.
    """
    if not intent or not isinstance(params, dict):
        return False

    required_cols = []
    if intent == "AGGREGATE":
        required_cols = [params.get("dimension"), params.get("metric")]
    elif intent == "VARIANCE":
        required_cols = [params.get("dimension"), params.get("period_a"), params.get("period_b")]
    elif intent == "FILTER_SORT":
        required_cols = [params.get("sort_col")] # Only sort_col is strictly required

    if not all(required_cols): # Check if any required param is missing
        return False

    for col_name in required_cols:
        if not aliases.resolve_column(col_name, column_names):
            logging.warning(f"Parameter validation failed: Could not resolve column '{col_name}' for intent '{intent}'.")
            return False

    return True

2. Implement the Soft-Accept Logic

File: backend/functions/orchestrator/main.py

Action: In the dispatcher logic within the _events generator, modify the routing condition.

# In main.py, inside the _events generator

intent = (classification or {}).get("intent") or "UNKNOWN"
params = (classification or {}).get("params") or {}
confidence = float((classification or {}).get("confidence") or 0.0)

# ---> ADD THIS LOGIC <---
params_are_valid = validate_params(intent, params, column_names)
soft_threshold = MIN_FASTPATH_CONFIDENCE - 0.15 # e.g., 0.50

is_fastpath_candidate = intent != "UNKNOWN" and (
    confidence >= MIN_FASTPATH_CONFIDENCE or 
    (confidence >= soft_threshold and params_are_valid)
)
# ---> END LOGIC <---

if FASTPATH_ENABLED and is_fastpath_candidate and (FORCE_FALLBACK_MIN_ROWS <= 0 or dataset_rows < FORCE_FALLBACK_MIN_ROWS):
    # ... (existing fast path logic) ...
