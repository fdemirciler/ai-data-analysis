"""
Analysis toolkit for fast-path deterministic operations.

Tools (v1):
- AGGREGATE: group by a dimension and aggregate a numeric metric with a function
- VARIANCE: compare two period columns aggregated by a dimension
- FILTER_SORT: optional filter then sort with limit
- DESCRIBE: basic dataset summary of numeric columns

All functions return a pandas.DataFrame.
"""
from __future__ import annotations

from typing import List, Optional
import pandas as pd
import numpy as np


TOOLKIT_VERSION = 1


def safe_numeric_cast(series: pd.Series, errors: str = "coerce") -> pd.Series:
    """Safely cast a series to numeric, replacing non-finite values with NaN then None where needed."""
    s = pd.to_numeric(series, errors=errors)
    return s


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
    """Optionally filter rows, then sort by sort_col and limit."""
    if sort_col not in df.columns:
        raise KeyError(f"Missing sort column: {sort_col}")

    dff = df
    if filter_col is not None and filter_val is not None:
        if filter_col not in df.columns:
            raise KeyError(f"Missing filter column: {filter_col}")
        dff = df[df[filter_col].astype(str) == str(filter_val)]

    # Prefer stable sort
    dff = dff.sort_values(by=sort_col, ascending=ascending, kind="mergesort")
    if limit and limit > 0:
        dff = dff.head(int(limit))
    return dff.reset_index(drop=True)


def run_describe(df: pd.DataFrame, include: str = "number") -> pd.DataFrame:
    """Describe numeric columns by default."""
    if include == "all":
        desc = df.describe(include="all").transpose()
    else:
        desc = df.select_dtypes(include=["number"]).describe().transpose()
    desc = desc.reset_index().rename(columns={"index": "column"})
    return desc


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
        "description": "Optionally filter rows, then sort and limit",
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
]
