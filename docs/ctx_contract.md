# ctx Contract

This document specifies the `ctx` object passed into the user-generated analysis function `def run(df, ctx):`.

The goals for `ctx` are:
- Provide enough context to generate compliant, efficient code.
- Enforce budget and safety constraints (time, memory, charts).
- Keep content compact and deterministic.

## Top-level structure

```json
{
  "dataset": {
    "rows": 0,
    "columns": 0,
    "column_names": ["..."],
    "dtypes": {"col": "dtype"}
  },
  "limits": {
    "maxCharts": 3,
    "timeBudgetSec": 10,
    "memoryMB": 512,
    "sampleRowsForDisplay": 50
  },
  "allowlist": [
    "pandas", "numpy", "matplotlib", "seaborn",
    "math", "statistics", "json", "io", "itertools", "functools", "collections", "re", "datetime"
  ],
  "provenance": {
    "sessionId": "...",
    "datasetId": "...",
    "messageId": "..."
  },
  "hazards": [
    "free_text:notes",
    "high_cardinality:segment"
  ],
  "chartability": {
    "numeric": ["revenue", "users"],
    "categorical_low_card": ["region"]
  },
  "cost": {
    "size_grade": "S",
    "est_rows_for_fast": 12500,
    "heavy_ops_caveat": ""
  },
  "seed": 42,
  "notes": [
    "No network access or file writes allowed.",
    "Prefer vectorized operations over loops.",
    "Avoid long-running operations."
  ]
}
```

## Field reference

- **dataset**
  - **rows**: Total number of rows in the cleaned dataset.
  - **columns**: Total number of columns in the cleaned dataset.
  - **column_names**: Ordered list of column names for the DataFrame.
  - **dtypes**: Mapping of column name to dtype string (e.g., `float64`, `int64`, `object`).

- **limits**
  - **maxCharts**: Maximum number of charts to produce (images returned as base64 PNG).
  - **timeBudgetSec**: Soft wall-clock budget; executors enforce hard timeouts.
  - **memoryMB**: Approximate memory budget for fast vs complex executors.
  - **sampleRowsForDisplay**: Maximum row count to include in small display tables.

- **allowlist**
  - Libraries and stdlib modules that may be imported by generated code. Any import outside this list fails validation.

- **provenance**
  - Identifiers useful for logging and correlating results.

- **hazards** (optional)
  - Flags derived from payload analysis (e.g., free-text columns, high cardinality) to steer safer code paths.

- **chartability** (optional)
  - Suggested columns that make good candidates for basic charts.

- **cost** (optional)
  - Hints about dataset size and expected fast-path capacity.

- **seed**
  - Fixed seed (e.g., 42) to ensure deterministic sampling and plotting randomness.

- **notes**
  - Additional guardrails or instructions for generated code.

## Example usage in `run(df, ctx)`

```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


def run(df, ctx):
    # Respect limits
    max_charts = ctx.get("limits", {}).get("maxCharts", 3)

    # Simple summary
    summary = f"Rows: {ctx['dataset']['rows']}, Cols: {ctx['dataset']['columns']}"

    # Example table (head limited by display budget)
    display_n = ctx.get("limits", {}).get("sampleRowsForDisplay", 50)
    table = df.head(min(5, display_n)).to_dict(orient="records")

    charts = []
    if max_charts > 0:
        # Example histogram if a numeric column exists
        numeric_cols = [c for c, t in ctx["dataset"]["dtypes"].items() if t.startswith("int") or t.startswith("float")]
        if numeric_cols:
            col = numeric_cols[0]
            import io, base64
            fig, ax = plt.subplots(figsize=(5, 3))
            df[col].dropna().hist(ax=ax, bins=20)
            ax.set_title(f"Histogram of {col}")
            buf = io.BytesIO()
            fig.tight_layout()
            fig.savefig(buf, format="png")
            plt.close(fig)
            png_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            charts.append({"png_base64": png_b64, "caption": f"Histogram of {col}"})

    return {
        "summary": summary,
        "tables": [table],
        "charts": charts,
        "notes": []
    }
```
