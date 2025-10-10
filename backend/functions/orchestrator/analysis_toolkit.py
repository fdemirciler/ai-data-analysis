"""
Analysis toolkit for fast-path deterministic operations.

Tools:
- AGGREGATE: group by a dimension and aggregate a numeric metric with a function
- VARIANCE: compare two period columns aggregated by a dimension
- FILTER_SORT (legacy): optional filter then sort with limit (delegates to FILTER + SORT)
- DESCRIBE: basic dataset summary of numeric columns

- FILTER: filter rows based on conditions
- SORT: stable sort by a column with an optional limit
- VALUE_COUNTS: frequency table for a column
- TOP_N_PER_GROUP: top/bottom N per group based on a metric
- PIVOT: pivot table across two categorical dimensions
- PERCENTILE: p-th percentile of a numeric column
- OUTLIERS: rows where a numeric column is an outlier (IQR or z-score)

All functions return a pandas.DataFrame.
"""
from __future__ import annotations

from typing import List, Optional, Any, Dict
import pandas as pd
import numpy as np


TOOLKIT_VERSION = 2


class ToolkitError(RuntimeError):
    """Custom exception for toolkit errors to provide clean, user-facing messages."""
    pass


def _require_columns(df: pd.DataFrame, *cols: str) -> None:
    """Raise ToolkitError if any required columns are missing."""
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ToolkitError(f"Missing required column(s): {', '.join(missing)}")


def safe_numeric_cast(series: pd.Series, errors: str = "coerce") -> pd.Series:
    """Safely cast a series to numeric, replacing non-finite values (inf/-inf) with NaN."""
    s = pd.to_numeric(series, errors=errors)
    return s.replace([np.inf, -np.inf], np.nan)


def run_aggregation(df: pd.DataFrame, dimension: str, metric: str, func: str) -> pd.DataFrame:
    """Aggregate metric by dimension using func in {sum, mean, avg, count, max, min}."""
    if func.lower() == "avg":
        agg_func = "mean"
    else:
        agg_func = func.lower()
    if agg_func not in {"sum", "mean", "count", "max", "min"}:
        raise ValueError(f"Unsupported aggregate function: {func}")

    if metric not in df.columns or dimension not in df.columns:
        raise KeyError("Missing required columns for aggregation")

    df2 = df[[dimension, metric]].copy()
    df2[metric] = safe_numeric_cast(df2[metric])
    grouped = df2.groupby(dimension, dropna=False)[metric].agg(agg_func).reset_index()
    grouped.columns = [dimension, f"{metric}_{agg_func}"]
    return grouped.sort_values(by=grouped.columns[1], ascending=False, kind="mergesort").reset_index(drop=True)


def run_variance(df: pd.DataFrame, dimension: str, period_a: str, period_b: str) -> pd.DataFrame:
    """Compare two numeric period columns aggregated by dimension. Returns delta and pct_change."""
    for col in (dimension, period_a, period_b):
        if col not in df.columns:
            raise KeyError(f"Missing required column: {col}")
    df2 = df[[dimension, period_a, period_b]].copy()
    df2[period_a] = safe_numeric_cast(df2[period_a])
    df2[period_b] = safe_numeric_cast(df2[period_b])
    grouped = df2.groupby(dimension, dropna=False).agg({period_a: "sum", period_b: "sum"}).reset_index()
    grouped["delta"] = grouped[period_b] - grouped[period_a]
    with np.errstate(divide="ignore", invalid="ignore"):
        grouped["pct_change"] = (grouped["delta"] / grouped[period_a]).replace([np.inf, -np.inf], np.nan) * 100.0
    return grouped.sort_values(by="delta", ascending=False, kind="mergesort").reset_index(drop=True)


def run_filter_and_sort(
    df: pd.DataFrame,
    sort_col: str,
    ascending: bool,
    limit: int,
    filter_col: Optional[str] = None,
    filter_val: Optional[str] = None,
) -> pd.DataFrame:
    """Optionally filter rows, then sort by sort_col and limit (legacy wrapper)."""
    if sort_col not in df.columns:
        raise KeyError(f"Missing sort column: {sort_col}")

    dff = df
    # Delegate filtering to new filter_rows if a filter is specified
    if filter_col is not None and filter_val is not None:
        if filter_col not in df.columns:
            raise KeyError(f"Missing filter column: {filter_col}")
        filters = [{"column": filter_col, "operator": "eq", "value": filter_val}]
        dff = filter_rows(df, filters=filters)

    # Delegate sorting (with limit) to new sort_rows
    dff = sort_rows(dff, sort_by_column=sort_col, ascending=ascending, limit=limit)
    return dff


def run_describe(df: pd.DataFrame, include: str = "number") -> pd.DataFrame:
    """Describe numeric columns by default."""
    if include == "all":
        desc = df.describe(include="all").transpose()
    else:
        desc = df.select_dtypes(include=["number"]).describe().transpose()
    desc = desc.reset_index().rename(columns={"index": "column"})
    return desc


# ----------------------- New deterministic verbs (v2) -----------------------

def filter_rows(df: pd.DataFrame, filters: List[Dict[str, Any]]) -> pd.DataFrame:
    """Filter rows using a list of conditions (AND logic across filters).

    Each filter item: {"column": str, "operator": str, "value": Any}
    Operators: eq, neq, gt, gte, lt, lte, is_in, contains (contains uses regex=False).
    """
    dff = df
    allowed = {"eq", "neq", "gt", "gte", "lt", "lte", "is_in", "contains"}
    for f in filters or []:
        col = f.get("column")
        op = str(f.get("operator") or "").lower()
        val = f.get("value")
        _require_columns(dff, col)
        if op not in allowed:
            raise ToolkitError(f"Unsupported operator: {op}")

        series = dff[col]
        if op in {"gt", "gte", "lt", "lte"}:
            series = safe_numeric_cast(series)
            try:
                num_val = float(val)
            except Exception:
                num_val = np.nan
            if op == "gt":
                dff = dff[series > num_val]
            elif op == "gte":
                dff = dff[series >= num_val]
            elif op == "lt":
                dff = dff[series < num_val]
            else:  # lte
                dff = dff[series <= num_val]
        elif op == "eq":
            dff = dff[series.astype(str) == str(val)]
        elif op == "neq":
            dff = dff[series.astype(str) != str(val)]
        elif op == "is_in":
            values = val if isinstance(val, (list, tuple, set)) else [val]
            dff = dff[series.astype(str).isin([str(v) for v in values])]
        elif op == "contains":
            dff = dff[series.astype(str).str.contains(str(val), na=False, regex=False)]
    return dff.reset_index(drop=True)


def sort_rows(df: pd.DataFrame, sort_by_column: str, ascending: bool = False, limit: int = 0) -> pd.DataFrame:
    """Stable sort by a column and optionally limit the number of rows."""
    _require_columns(df, sort_by_column)
    dff = df.sort_values(by=sort_by_column, ascending=ascending, kind="mergesort")
    if limit and limit > 0:
        dff = dff.head(int(limit))
    return dff.reset_index(drop=True)


def value_counts(df: pd.DataFrame, column: str, top: int = 100, include_pct: bool = True) -> pd.DataFrame:
    """Frequency table of a column with optional percentage; clamps top to [1..10000]."""
    _require_columns(df, column)
    try:
        top_int = int(top)
    except Exception:
        top_int = 100
    top_int = max(1, min(10000, top_int))
    counts = df[column].value_counts(dropna=False).head(top_int).reset_index()
    counts.columns = [column, "count"]
    if include_pct:
        total = max(1, len(df))
        counts["pct"] = (counts["count"] / total * 100).round(2)
    return counts.reset_index(drop=True)


def top_n_per_group(df: pd.DataFrame, group_by_column: str, metric_column: str, n: int = 5, ascending: bool = False) -> pd.DataFrame:
    """Returns the top or bottom N rows for each group based on a metric."""
    _require_columns(df, group_by_column, metric_column)
    df2 = df.copy()
    df2[metric_column] = safe_numeric_cast(df2[metric_column])
    out = (
        df2.sort_values(by=metric_column, ascending=ascending)
        .groupby(group_by_column, dropna=False)
        .head(int(n))
        .reset_index(drop=True)
    )
    return out


def pivot_table(df: pd.DataFrame, index: str, columns: str, values: str, aggfunc: str = "sum") -> pd.DataFrame:
    """Creates a pivot table summarizing a numeric values column across two categorical dimensions."""
    if df.empty:
        return df.copy()
    _require_columns(df, index, columns, values)
    df2 = df.copy()
    df2[values] = safe_numeric_cast(df2[values])
    pivot = df2.pivot_table(index=index, columns=columns, values=values, aggfunc=aggfunc, fill_value=0)
    return pivot.reset_index()


def percentile(df: pd.DataFrame, column: str, p: Any) -> pd.DataFrame:
    """Single-row DataFrame with the p-th percentile of a numeric column (0 ≤ p ≤ 100)."""
    _require_columns(df, column)
    try:
        p_float = float(p)
    except Exception:
        raise ToolkitError("Percentile 'p' must be a number")
    if not (0.0 <= p_float <= 100.0):
        raise ToolkitError("Percentile 'p' must be between 0 and 100")
    s = safe_numeric_cast(df[column])
    val = float(np.nanpercentile(s.to_numpy(dtype=float), p_float))
    return pd.DataFrame({f"{column}_p{int(p_float) if p_float.is_integer() else p_float}": [val]})


def outliers(df: pd.DataFrame, column: str, method: str = "iqr", k: Any = 1.5) -> pd.DataFrame:
    """Return rows whose column is an outlier using IQR or z-score method."""
    _require_columns(df, column)
    s = safe_numeric_cast(df[column])
    try:
        kf = float(k)
    except Exception:
        kf = 1.5
    method_l = (method or "iqr").lower()
    if method_l == "iqr":
        q1, q3 = np.nanpercentile(s.to_numpy(dtype=float), [25, 75])
        iqr = q3 - q1
        mask = (s < (q1 - kf * iqr)) | (s > (q3 + kf * iqr))
    else:  # zscore
        mu = float(np.nanmean(s.to_numpy(dtype=float)))
        sigma = float(np.nanstd(s.to_numpy(dtype=float))) or np.nan
        with np.errstate(divide="ignore", invalid="ignore"):
            z = (s - mu) / sigma
        mask = np.abs(z) > kf
    return df[mask].reset_index(drop=True)


# Tools spec for Gemini native function-calling (snake_case)
TOOLS_SPEC = [
    {
        "name": "run_aggregation",
        "description": "Group by a dimension and aggregate a numeric metric with a function",
        "parameters": {
            "type": "object",
            "properties": {
                "dimension": {"type": "string", "description": "Column to group by"},
                "metric": {"type": "string", "description": "Numeric column to aggregate"},
                "func": {"type": "string", "enum": ["sum", "mean", "count", "max", "min"], "description": "Aggregation function"},
            },
            "required": ["dimension", "metric", "func"],
        },
    },
    {
        "name": "run_variance",
        "description": "Calculate difference and % change between two numeric period columns grouped by a dimension",
        "parameters": {
            "type": "object",
            "properties": {
                "dimension": {"type": "string", "description": "Group key column"},
                "period_a": {"type": "string", "description": "First period column (earlier)"},
                "period_b": {"type": "string", "description": "Second period column (later)"},
            },
            "required": ["dimension", "period_a", "period_b"],
        },
    },
    {
        "name": "run_filter_and_sort",
        "description": "Optionally filter rows, then sort and limit (legacy; delegates to FILTER + SORT)",
        "parameters": {
            "type": "object",
            "properties": {
                "sort_col": {"type": "string", "description": "Column to sort by"},
                "ascending": {"type": "boolean", "description": "True for ascending"},
                "limit": {"type": "integer", "description": "Row limit"},
                "filter_col": {"type": "string", "description": "Optional filter column"},
                "filter_val": {"type": "string", "description": "Optional filter value"},
            },
            "required": ["sort_col", "ascending", "limit"],
        },
    },
    {
        "name": "run_describe",
        "description": "Summarize numeric columns with count, mean, std, min, max",
        "parameters": {"type": "object", "properties": {}},
    },
    # New tools (v2)
    {
        "name": "filter_rows",
        "description": "Filter rows based on a list of conditions (AND across filters).",
        "parameters": {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "operator": {"type": "string", "enum": ["eq", "neq", "gt", "gte", "lt", "lte", "is_in", "contains"]},
                            "value": {}
                        },
                        "required": ["column", "operator", "value"]
                    }
                }
            },
            "required": ["filters"]
        }
    },
    {
        "name": "sort_rows",
        "description": "Stable sort by a column with optional limit.",
        "parameters": {
            "type": "object",
            "properties": {
                "sort_by_column": {"type": "string"},
                "ascending": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 0, "default": 0}
            },
            "required": ["sort_by_column"]
        }
    },
    {
        "name": "value_counts",
        "description": "Frequency table for a column (optionally with percentage).",
        "parameters": {
            "type": "object",
            "properties": {
                "column": {"type": "string"},
                "top": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 100},
                "include_pct": {"type": "boolean", "default": True}
            },
            "required": ["column"]
        }
    },
    {
        "name": "top_n_per_group",
        "description": "Top or bottom N rows within each group based on a metric.",
        "parameters": {
            "type": "object",
            "properties": {
                "group_by_column": {"type": "string"},
                "metric_column": {"type": "string"},
                "n": {"type": "integer", "minimum": 1, "default": 5},
                "ascending": {"type": "boolean", "default": False}
            },
            "required": ["group_by_column", "metric_column"]
        }
    },
    {
        "name": "pivot_table",
        "description": "Pivot a numeric values column across two categorical dimensions.",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {"type": "string"},
                "columns": {"type": "string"},
                "values": {"type": "string"},
                "aggfunc": {"type": "string", "enum": ["sum", "mean", "median", "count"], "default": "sum"}
            },
            "required": ["index", "columns", "values"]
        }
    },
    {
        "name": "percentile",
        "description": "Compute the p-th percentile (0..100) for a numeric column.",
        "parameters": {
            "type": "object",
            "properties": {
                "column": {"type": "string"},
                "p": {"type": "number", "minimum": 0, "maximum": 100}
            },
            "required": ["column", "p"]
        }
    },
    {
        "name": "outliers",
        "description": "Rows where a numeric column is an outlier by IQR or z-score.",
        "parameters": {
            "type": "object",
            "properties": {
                "column": {"type": "string"},
                "method": {"type": "string", "enum": ["iqr", "zscore"], "default": "iqr"},
                "k": {"type": "number", "default": 1.5}
            },
            "required": ["column"]
        }
    },
]
