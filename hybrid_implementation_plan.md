*** Plan 1 ***

# Implementation Plan: Hybrid "Smart Dispatcher" Analysis Pipeline

## 1. Purpose and Rationale

The current chatbot architecture relies heavily on **monolithic code generation** for every user query. This results in high latency, brittleness, and complex error handling when the LLM-generated Python code fails to execute correctly.  
Our goal is to evolve toward a **hybrid, production-grade architecture** that combines **deterministic tool execution** (fast, reliable) with **flexible code generation fallback** (for complex or unknown intents).

### Objectives
- Build a **fast and secure** analysis engine using pre-written Python functions.
- Retain the **transparency feature** ("Show me the code") for user trust.
- Enable **incremental extensibility** — new tools can be added easily over time.
- Keep infrastructure **simple and low-cost**, using only GCS and free-tier services.

---

## 2. Proposed Hybrid Workflow

### A. Fast Path – Function-Calling Execution
1. **Intent Classification:** The LLM converts the user’s question and data schema into a JSON command:
   ```json
   {"intent": "VARIANCE", "params": {"dimension": "Product", "periods": ["2023", "2024"]}}
   ```
2. **Deterministic Execution:** The backend executes the mapped Python function from `analysis_toolkit.py` (no LLM-generated code).
3. **Formatting:** The result DataFrame is passed to Gemini to produce a summary and visualization spec (JSON for tables/charts).
4. **Response Rendering:** The frontend displays the summary and visuals.

### B. Fallback Path – Code Generation
If the LLM cannot classify the intent (returns `"UNKNOWN"`) or the toolkit lacks the needed function:
1. Fall back to the **old code generation flow** (Python script creation, AST validation, and sandboxed execution).
2. Cache the script and results in GCS.

### C. “Show Me the Code” Transparency Feature
When the user requests “Show me the code”:
1. Retrieve the stored JSON command from Firestore.
2. Call Gemini to **reconstruct a clean, readable Python script** replicating the logic of the executed toolkit function.
3. Return this script to the frontend in a new SSE event (`"code"`).

---

## 3. Implementation Tasks

### Task 1: Create the Core Analysis Toolkit
**File:** `backend/functions/orchestrator/analysis_toolkit.py`

- Implement deterministic, pre-written analysis functions.
- Each function must:
  - Accept a pandas DataFrame and params dict.
  - Return a DataFrame.
  - Handle errors gracefully.

**Initial Functions**
```python
def run_aggregation(df, dimension, metric, func): ...
def run_variance(df, dimension, periods): ...
def run_filter_and_sort(df, sort_col, ascending, limit, filter_col=None, filter_val=None): ...
```

**Subtasks**
- [ ] Create the file.
- [ ] Populate with initial 3 functions.
- [ ] Add a registry dictionary (e.g., `TOOLS = {"AGGREGATE": run_aggregation, "VARIANCE": run_variance, "FILTER_SORT": run_filter_and_sort}`).
- [ ] Add logging and error handling for tracing execution.

---

### Task 2: Refactor the Orchestrator and Gemini Client

#### Subtask 2.1: Intent Classification
**File:** `backend/functions/orchestrator/gemini_client.py`
- Add `classify_intent(question, schema_snippet)`.
- Gemini should return a compact JSON object with `intent` and `params`.

#### Subtask 2.2: Response Formatting
**File:** `backend/functions/orchestrator/gemini_client.py`
- Add `format_final_response(question, result_df)`.
- Output JSON like:
  ```json
  {
    "summary": "Revenue grew 8% YoY.",
    "visuals": [
      {"type": "table", "data": {...}},
      {"type": "chart", "spec": {...}}
    ]
  }
  ```

#### Subtask 2.3: Main Orchestrator Overhaul
**File:** `backend/functions/orchestrator/main.py`
- Replace old logic with a new “Smart Dispatcher” loop:
  1. Parse user message.
  2. If `message == "show me the code"` → run reconstruction path.
  3. Else:
     - Call `classify_intent()`.
     - If valid → call toolkit function via dispatcher.
     - Else → fallback to old code-generation flow.
     - Send formatted results to frontend via SSE.

#### Subtask 2.4: Clean-Up
Delete obsolete files:
```
backend/functions/orchestrator/worker.py
backend/functions/orchestrator/sandbox_runner.py
backend/shared/ast_validator.py
```

---

### Task 3: Implement the “Show Me the Code” Flow

#### Subtask 3.1: Code Reconstruction
**File:** `backend/functions/orchestrator/gemini_client.py`
- Add `reconstruct_code(command, schema_snippet)` — instructs Gemini to generate a readable Python script.

#### Subtask 3.2: Persist Commands
**File:** `backend/functions/orchestrator/main.py`
- Save each JSON command to Firestore under the message document.

#### Subtask 3.3: Retrieve and Stream Code
**File:** `backend/functions/orchestrator/main.py`
- On `"show me the code"`, fetch previous command and call `reconstruct_code()`.
- Return via new event type `"code"`.

---

### Task 4: Update Frontend Components

#### Subtask 4.1: Stream Event Handling
**File:** `frontend/src/App.tsx`
- Adjust `onEvent` handler to process:
  - `summary` text.
  - `visuals[]` array (tables/charts).
  - `code` event for reconstructed scripts.

#### Subtask 4.2: Markdown Renderer
**File:** `frontend/src/components/renderers/MarkdownRenderer.tsx`
- Use `react-markdown` to display Markdown or preformatted HTML safely.

#### Subtask 4.3: “Show Code” Button
**File:** `frontend/src/components/ChatMessage.tsx`
- Add a “Show Code” button after assistant summary.
- When clicked → triggers `onSendMessage("show me the code")`.

---

### Task 5: Data Exchange Model & Storage Integration

#### Subtask 5.1: Temporary Artifact Storage
- Use **GCS temporary JSON files** to store intermediate results.
- Schema:
  ```json
  {
    "intent": "VARIANCE",
    "params": {...},
    "timestamp": "...",
    "gcs_ref": "gs://your-bucket/session123/result.json"
  }
  ```

#### Subtask 5.2: Data Passing Between Stages
- Internal data: pandas DataFrame.
- Cross-stage data: JSON or Arrow-serialized tables.
- LLM communication: JSON envelopes (never raw DataFrames).

---

## 4. Toolkit Starter Functions

Below are initial functions you can directly copy to `analysis_toolkit.py`.

```python
import pandas as pd

AGG_FUNCS = {
    'sum': 'sum',
    'avg': 'mean',
    'mean': 'mean',
    'count': 'count',
    'max': 'max',
    'min': 'min'
}

def run_aggregation(df, dimension, metric, func):
    if dimension not in df or metric not in df:
        raise ValueError("Missing columns for aggregation.")
    df[metric] = pd.to_numeric(df[metric], errors='coerce')
    agg_df = df.dropna(subset=[metric]).groupby(dimension, as_index=False)[metric].agg(AGG_FUNCS.get(func, 'sum'))
    return agg_df.sort_values(by=metric, ascending=False)

def run_variance(df, dimension, periods):
    if len(periods) != 2:
        raise ValueError("Exactly two period columns required.")
    p1, p2 = periods
    for col in [dimension, p1, p2]:
        if col not in df: raise ValueError(f"Missing column {col}")
    df[p1] = pd.to_numeric(df[p1], errors='coerce')
    df[p2] = pd.to_numeric(df[p2], errors='coerce')
    out = df[[dimension, p1, p2]].copy()
    out["Variance"] = out[p1] - out[p2]
    out["% Change"] = (out["Variance"] / out[p2].replace(0, pd.NA)) * 100
    return out.sort_values(by="Variance", key=abs, ascending=False)

def run_filter_and_sort(df, sort_col, ascending=True, limit=10, filter_col=None, filter_val=None):
    if sort_col not in df: raise ValueError(f"Sort column '{sort_col}' not found.")
    df_filtered = df.copy()
    if filter_col and filter_val and filter_col in df:
        df_filtered = df_filtered[df_filtered[filter_col].astype(str).str.contains(str(filter_val), case=False, na=False)]
    return df_filtered.sort_values(by=sort_col, ascending=ascending).head(limit)
```

---

## 5. Next Steps

1. Implement Task 1 (Toolkit) and Task 2 (Dispatcher).
2. Test using sample queries for “sum by region” and “variance between periods”.
3. Once stable, connect frontend and deploy the hybrid pipeline.

---

## 6. Benefits of the New Architecture

- **Speed:** Function calls avoid sandboxing overhead.
- **Reliability:** Strict tool execution reduces LLM unpredictability.
- **Transparency:** Users can still “see the code” via reconstruction.
- **Security:** No arbitrary Python execution in fast path.
- **Maintainability:** Toolkit functions can be unit-tested independently.

*** Plan 2 ***

Implementation Plan: Migrating to the Hybrid "Smart Dispatcher" Architecture
1. Purpose and Goal
Current Situation
Our current chatbot operates on a monolithic code-generation model. For every query, it prompts Gemini to generate a full Python script, which is then validated and executed in a sandbox. While flexible, this approach is slow, prone to errors, and can hang if the LLM's output deviates even slightly from the expected schema.

Proposed Architecture: The Hybrid Model
This document outlines the plan to refactor the backend into a robust hybrid system. This architecture will use fast, reliable, pre-written function calls for common analysis tasks and only fall back to sandboxed code generation for complex or unknown queries.

This hybrid model delivers a superior user experience by providing:

⚡ Speed: Common queries are answered almost instantly by deterministic code.

🧱 Reliability: The vast majority of requests will follow a predictable, error-free path.

🧠 Transparency: Users can still ask "Show me the code," and the system will generate a clean, explanatory Python script on-demand, even for analyses that were performed via function call.

🧰 Extensibility: New analysis capabilities can be added by simply writing a new function, without complex prompt engineering.

2. High-Level Workflow
The new workflow in the orchestrator will be as follows:

Intent Routing (LLM Call #1): A fast Gemini call will analyze the user's query and the data schema. It will decide whether to use a pre-defined function ("tool") or fall back to generating code.

Execution:

Fast Path: If a tool is chosen, the orchestrator executes your pre-written Python function from a new Analysis Toolkit. This is fast, secure, and doesn't require a sandbox.

Fallback Path: If no tool matches, the system uses the existing (but now secondary) code-generation-and-sandbox flow.

Synthesis & Formatting (LLM Call #2): The clean data result from either path is sent to Gemini to generate a human-readable summary and format the data for frontend visualization (e.g., as a Markdown table or a chart specification).

On-Demand Code Reconstruction: The intent and parameters from the "Fast Path" are saved. If the user asks to see the code, a final LLM call reconstructs an explanatory Python script based on that saved context.

3. Detailed Implementation Tasks
This plan is broken down into a series of actionable tasks.

Task 1: Create the Core Analysis Toolkit
This is the foundation of our "fast path." We will create a library of trusted Python functions to handle common analyses.

Sub-task 1.1: Create a new file for the toolkit.

Action: In backend/functions/orchestrator/, create a new file named analysis_toolkit.py.

Purpose: This file will house all our pre-written, deterministic analysis functions. You can use the code provided in Appendix A of this document as a direct starting point.

Sub-task 1.2: Define the TOOL_SPEC in the new file.

Action: At the top of analysis_toolkit.py, define a TOOL_SPEC list. This is the "menu" of tools that you will provide to the Gemini model so it knows what functions are available.

Example:

TOOL_SPEC = [
    {
        "name": "run_aggregation",
        "description": "Performs groupby aggregation (sum, average, count) on a metric, grouped by a dimension.",
        "parameters": { ... }
    },
    # ... other tool definitions
]

Task 2: Refactor the Orchestrator and Gemini Client
This is the core of the refactoring, replacing the old pipeline with the new hybrid logic.

Sub-task 2.1: Create the new "Router" function in gemini_client.py.

File: backend/functions/orchestrator/gemini_client.py

Action: Create a new function route_user_query(question, schema_snippet, tool_spec). This function will use Gemini's function-calling capabilities to decide which tool to use, or if it should fall back to code generation.

Prompt Goal: Instruct the LLM to choose a tool from the provided tool_spec. If no tool is appropriate, it should return a specific response indicating a fallback is needed.

Sub-task 2.2: Create the "Response Formatter" function.

File: backend/functions/orchestrator/gemini_client.py

Action: Create a function format_final_response(question, result_df). This takes the final, clean DataFrame from the execution stage and asks Gemini to produce the final JSON payload containing the summary and visuals array.

Sub-task 2.3: Rewrite the main orchestrator logic in main.py.

File: backend/functions/orchestrator/main.py

Action: Overhaul the _events generator function.

Remove the old logic: Delete the calls to generate_code_and_summary, sandbox_runner.validate_code, the subprocess call to worker.py, and the entire repair loop.

Implement the hybrid flow:

Call your new gemini_client.route_user_query.

If a tool is returned:

Save the tool name and parameters to Firestore for the "Show Code" feature.

Call the corresponding function from analysis_toolkit.

If a fallback is indicated:

(Optional for now) Trigger the old generate_analysis_code and run it in a sandbox. For the initial implementation, you can simply return a message like "I'm not sure how to answer that."

Pass the resulting DataFrame to gemini_client.format_final_response.

Send the final payload in the done event.

Sub-task 2.4: Clean up unused files.

Action: The following files are now obsolete and can be safely deleted:

backend/functions/orchestrator/worker.py

backend/functions/orchestrator/sandbox_runner.py

backend/shared/ast_validator.py

Task 3: Implement the "Show Me the Code" Feature
This task adds the on-demand code reconstruction.

Sub-task 3.1: Create the "Code Reconstruction" function.

File: backend/functions/orchestrator/gemini_client.py

Action: Add a function reconstruct_code_from_tool_call(tool_name, params, schema_snippet). This will take the saved tool context and prompt Gemini to generate a clean, human-readable Python script that replicates the tool's logic.

Sub-task 3.2: Handle the "Show Code" request in main.py.

File: backend/functions/orchestrator/main.py

Action: At the start of the _events generator, add a check: if question.lower().strip() == "show me the code", trigger the reconstruction flow.

Fetch the tool_name and params from the previous message's Firestore document.

Call gemini_client.reconstruct_code_from_tool_call.

Stream back a single code event with the generated script and then terminate the stream.

Task 4: Update the Frontend
The frontend requires minor changes to handle the new payload and add the "Show Code" button.

Sub-task 4.1: Adapt App.tsx to the new done event payload.

The done event will now contain a summary and a visuals array.

In the onEvent handler, update the placeholder message with the summary. Then, iterate through the visuals array and append new message bubbles for each item (one for markdown_table, one for chart_spec).

Sub-task 4.2: Create a Markdown renderer.

Create a new component MarkdownRenderer.tsx. This component will take a Markdown string and render it as HTML (you can use a library like react-markdown).

Update ChatMessage.tsx to use this new component for a new message kind: "markdown".

Sub-task 4.3: Add a "Show Code" button in ChatMessage.tsx.

After an assistant message that contains a summary, display a simple "Show Code" button.

On click, this button should call onSendMessage("show me the code"), which will trigger the reconstruction flow on the backend.

Appendix A: Starter analysis_toolkit.py
You can use this code as the starting content for backend/functions/orchestrator/analysis_toolkit.py.

# backend/functions/orchestrator/analysis_toolkit.py

"""
Core Analysis Toolkit

This module contains a library of pre-written, deterministic data analysis
functions. The main orchestrator calls these functions based on the classified
intent from the user's query.

Each function should:
- Accept a pandas DataFrame as its first argument.
- Accept parameters extracted from the user's query.
- Perform a single, well-defined analysis task.
- Return a pandas DataFrame containing the results.
- Be robust and handle potential errors gracefully (e.g., missing columns).
"""

import pandas as pd
from typing import List, Literal

# A dictionary to map user-friendly function names to pandas aggregation functions
AGGREGATION_MAP = {
    'sum': 'sum',
    'average': 'mean',
    'mean': 'mean',
    'count': 'count',
    'median': 'median',
    'min': 'min',
    'max': 'max'
}

def run_aggregation(
    df: pd.DataFrame, 
    dimension: str, 
    metric: str, 
    func: str
) -> pd.DataFrame:
    """
    Performs a groupby aggregation on the DataFrame.

    Handles questions like:
    - "What is the total revenue by region?"
    - "Show me the average cost per product."

    Args:
        df: The input DataFrame.
        dimension: The column to group by (e.g., 'Region').
        metric: The column to aggregate (e.g., 'Revenue').
        func: The aggregation function to apply ('sum', 'mean', 'count', etc.).

    Returns:
        A DataFrame with the aggregated results.
    """
    if dimension not in df.columns:
        raise ValueError(f"Dimension column '{dimension}' not found in the dataset.")
    if metric not in df.columns:
        raise ValueError(f"Metric column '{metric}' not found in the dataset.")

    agg_func = AGGREGATION_MAP.get(func.lower())
    if not agg_func:
        raise ValueError(f"Unsupported aggregation function: '{func}'. Supported functions are: {list(AGGREGATION_MAP.keys())}")

    # Ensure the metric column is numeric before aggregating
    df[metric] = pd.to_numeric(df[metric], errors='coerce')
    
    # Drop rows where the metric is NaN after coercion to avoid issues with aggregation
    agg_df = df.dropna(subset=[metric])

    result = agg_df.groupby(dimension, as_index=False)[metric].agg(agg_func)
    
    # Rename the metric column to be more descriptive
    result.rename(columns={metric: f'{metric.capitalize()} ({func.capitalize()})'}, inplace=True)

    return result.sort_values(by=result.columns[1], ascending=False)


def run_variance(
    df: pd.DataFrame, 
    dimension: str, 
    periods: List[str]
) -> pd.DataFrame:
    """
    Calculates the variance (difference) between two period columns.

    Handles questions like:
    - "Compare sales between 2023 and 2024."
    - "Show the variance in profit for the last two periods."

    Args:
        df: The input DataFrame.
        dimension: The column that identifies the items being compared (e.g., 'Product').
        periods: A list of two column names representing the time periods.

    Returns:
        A DataFrame showing the values for both periods and their variance.
    """
    if len(periods) != 2:
        raise ValueError(f"Variance calculation requires exactly two periods, but got {len(periods)}.")
    
    # Ensure periods are sorted chronologically if they are year-like strings
    try:
        sorted_periods = sorted(periods, key=lambda x: int(x), reverse=True)
        period1, period2 = sorted_periods[0], sorted_periods[1] # e.g., '2024', '2023'
    except ValueError:
        # If not integer-like, just use the order given
        period1, period2 = periods[0], periods[1]

    if dimension not in df.columns:
        raise ValueError(f"Dimension column '{dimension}' not found.")
    if period1 not in df.columns:
        raise ValueError(f"Period column '{period1}' not found.")
    if period2 not in df.columns:
        raise ValueError(f"Period column '{period2}' not found.")

    # Select relevant columns and ensure periods are numeric
    result_df = df[[dimension, period1, period2]].copy()
    result_df[period1] = pd.to_numeric(result_df[period1], errors='coerce')
    result_df[period2] = pd.to_numeric(result_df[period2], errors='coerce')

    # Calculate variance and percentage change
    result_df['Variance'] = result_df[period1] - result_df[period2]
    # Avoid division by zero for percentage change calculation
    result_df['% Change'] = (result_df['Variance'] / result_df[period2].abs()).replace([float('inf'), -float('inf')], 0) * 100

    return result_df.sort_values(by='Variance', key=abs, ascending=False)


def run_filter_and_sort(
    df: pd.DataFrame, 
    sort_col: str, 
    ascending: bool, 
    limit: int,
    filter_col: str = None,
    filter_val: str = None
) -> pd.DataFrame:
    """
    Filters (optional) and sorts a DataFrame.

    Handles questions like:
    - "Show me the top 10 most profitable items."
    - "List all transactions in the 'North' region, sorted by date."

    Args:
        df: The input DataFrame.
        sort_col: The column to sort by.
        ascending: Boolean indicating sort direction.
        limit: The number of rows to return.
        filter_col: (Optional) The column to apply a filter on.
        filter_val: (Optional) The value to filter for in `filter_col`.

    Returns:
        A filtered and sorted DataFrame.
    """
    if sort_col not in df.columns:
        raise ValueError(f"Sort column '{sort_col}' not found.")

    filtered_df = df.copy()

    # Apply filter if both filter_col and filter_val are provided
    if filter_col and filter_val is not None:
        if filter_col not in df.columns:
            raise ValueError(f"Filter column '{filter_col}' not found.")
        # Perform a case-insensitive filter for string columns
        if pd.api.types.is_string_dtype(filtered_df[filter_col]):
            filtered_df = filtered_df[filtered_df[filter_col].str.contains(str(filter_val), case=False, na=False)]
        else:
            # Attempt to cast filter value for numeric/other types
            try:
                # Get the type of the first non-null value in the column
                col_type = type(filtered_df[filter_col].dropna().iloc[0])
                cast_val = col_type(filter_val)
                filtered_df = filtered_df[filtered_df[filter_col] == cast_val]
            except (ValueError, IndexError):
                # If casting fails or column is all null, filter by string representation
                filtered_df = filtered_df[filtered_df[filter_col].astype(str).str.lower() == str(filter_val).lower()]
    
    # Sort the data
    sorted_df = filtered_df.sort_values(by=sort_col, ascending=ascending)

    return sorted_df.head(limit)

