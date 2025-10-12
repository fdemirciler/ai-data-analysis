"""
Analysis toolkit for fast-path deterministic operations.

Enhanced v2 with improved function definitions, consistent naming,
and expanded capabilities to minimize fallback usage.

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
        available = list(df.columns)[:10]  # Show first 10 for context
        raise ToolkitError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Available columns: {', '.join(available)}..."
        )


def safe_numeric_cast(series: pd.Series, errors: str = "coerce") -> pd.Series:
    """Safely cast a series to numeric, replacing non-finite values (inf/-inf) with NaN."""
    s = pd.to_numeric(series, errors=errors)
    return s.replace([np.inf, -np.inf], np.nan)


# ============================================================================
# LEGACY FUNCTIONS (Maintained for backward compatibility)
# ============================================================================

def run_aggregation(df: pd.DataFrame, dimension: str, metric: str, func: str) -> pd.DataFrame:
    """Group by a dimension and aggregate a metric with a function.
    
    Args:
        dimension: Column to group by
        metric: Numeric column to aggregate
        func: Aggregation function (sum, mean, avg, count, max, min)
    
    Returns:
        DataFrame with columns: [dimension, metric_{func}], sorted by aggregated value descending
    
    Example:
        >>> run_aggregation(df, "region", "revenue", "sum")
        # Returns total revenue per region, highest first
    """
    if func.lower() == "avg":
        agg_func = "mean"
    else:
        agg_func = func.lower()
    
    if agg_func not in {"sum", "mean", "count", "max", "min"}:
        raise ToolkitError(f"Unsupported aggregate function: {func}. Use: sum, mean, count, max, min")

    _require_columns(df, dimension, metric)

    df2 = df[[dimension, metric]].copy()
    df2[metric] = safe_numeric_cast(df2[metric])
    grouped = df2.groupby(dimension, dropna=False)[metric].agg(agg_func).reset_index()
    grouped.columns = [dimension, f"{metric}_{agg_func}"]
    return grouped.sort_values(by=grouped.columns[1], ascending=False, kind="mergesort").reset_index(drop=True)


def run_variance(df: pd.DataFrame, dimension: str, period_a: str, period_b: str) -> pd.DataFrame:
    """Calculate difference and percentage change between two period columns grouped by dimension.
    
    Args:
        dimension: Group key column
        period_a: First period column (earlier/baseline)
        period_b: Second period column (later/comparison)
    
    Returns:
        DataFrame with columns: [dimension, period_a, period_b, delta, pct_change]
        Sorted by delta descending
    
    Example:
        >>> run_variance(df, "product", "sales_2023", "sales_2024")
        # Shows which products grew/declined the most
    """
    _require_columns(df, dimension, period_a, period_b)
    
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
    """[DEPRECATED] Optionally filter rows, then sort and limit.
    
    Use filter_rows() + sort_rows() instead for better composability.
    Maintained for backward compatibility.
    """
    _require_columns(df, sort_col)
    
    dff = df
    if filter_col is not None and filter_val is not None:
        _require_columns(df, filter_col)
        filters = [{"column": filter_col, "operator": "eq", "value": filter_val}]
        dff = filter_rows(df, filters=filters)

    dff = sort_rows(dff, sort_by_column=sort_col, ascending=ascending, limit=limit)
    return dff


def run_describe(df: pd.DataFrame, include: str = "number", group_by: Optional[str] = None) -> pd.DataFrame:
    """Generate summary statistics for numeric columns.
    
    Args:
        include: "number" (numeric only) or "all" (include categorical)
        group_by: Optional column to group by before describing
    
    Returns:
        Transposed description with column names as rows
    
    Example:
        >>> run_describe(df)
        # Returns count, mean, std, min, 25%, 50%, 75%, max for each numeric column
        
        >>> run_describe(df, group_by="region")
        # Returns statistics per region
    """
    if group_by:
        _require_columns(df, group_by)
        if include == "all":
            desc = df.groupby(group_by, dropna=False).describe(include="all")
        else:
            numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
            if not numeric_cols:
                raise ToolkitError("No numeric columns found for description")
            desc = df.groupby(group_by, dropna=False)[numeric_cols].describe()
        return desc.reset_index()
    
    if include == "all":
        desc = df.describe(include="all").transpose()
    else:
        numeric_df = df.select_dtypes(include=["number"])
        if numeric_df.empty:
            raise ToolkitError("No numeric columns found for description")
        desc = numeric_df.describe().transpose()
    
    desc = desc.reset_index().rename(columns={"index": "column"})
    return desc


# ============================================================================
# CORE DATA MANIPULATION (v2)
# ============================================================================

def filter_rows(df: pd.DataFrame, filters: List[Dict[str, Any]]) -> pd.DataFrame:
    """Filter rows using a list of conditions (AND logic across filters).
    
    Args:
        filters: List of filter dicts, each with keys:
            - column: str (column name)
            - operator: str (eq, neq, gt, gte, lt, lte, is_in, contains)
            - value: Any (value to compare against)
    
    Returns:
        Filtered DataFrame
    
    Example:
        >>> filter_rows(df, [
        ...     {"column": "region", "operator": "eq", "value": "North"},
        ...     {"column": "revenue", "operator": "gt", "value": 1000}
        ... ])
        # Returns rows where region='North' AND revenue>1000
    """
    dff = df
    allowed = {"eq", "neq", "gt", "gte", "lt", "lte", "is_in", "contains"}
    
    for f in filters or []:
        col = f.get("column")
        op = str(f.get("operator") or "").lower()
        val = f.get("value")
        
        _require_columns(dff, col)
        
        if op not in allowed:
            raise ToolkitError(f"Unsupported operator: {op}. Use: {', '.join(sorted(allowed))}")

        series = dff[col]
        
        if op in {"gt", "gte", "lt", "lte"}:
            series = safe_numeric_cast(series)
            try:
                num_val = float(val)
            except Exception:
                raise ToolkitError(f"Cannot convert '{val}' to numeric for comparison")
            
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
    """Stable sort by a column with optional limit.
    
    Args:
        sort_by_column: Column to sort by
        ascending: True for ascending (low to high), False for descending (high to low)
        limit: Optional row limit (0 = no limit)
    
    Returns:
        Sorted DataFrame
    
    Example:
        >>> sort_rows(df, "revenue", ascending=False, limit=10)
        # Returns top 10 rows by revenue
    """
    _require_columns(df, sort_by_column)
    dff = df.sort_values(by=sort_by_column, ascending=ascending, kind="mergesort")
    
    if limit and limit > 0:
        dff = dff.head(int(limit))
    
    return dff.reset_index(drop=True)


# ============================================================================
# FREQUENCY & DISTRIBUTION
# ============================================================================

def value_counts(df: pd.DataFrame, column: str, top: int = 100, include_pct: bool = True) -> pd.DataFrame:
    """Frequency table of a column with optional percentage.
    
    Args:
        column: Column to count
        top: Maximum rows to return (1-10000)
        include_pct: Whether to include percentage column
    
    Returns:
        DataFrame with columns: [column, count, pct (optional)]
        Sorted by count descending
    
    Example:
        >>> value_counts(df, "category", top=5)
        # Shows top 5 most frequent categories with percentages
    """
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


def missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Summary of missing values per column.
    
    Returns:
        DataFrame with columns: [column, missing_count, missing_pct]
        Only includes columns with missing values, sorted by count descending
    
    Example:
        >>> missing_values(df)
        # Shows which columns have nulls and how many
    """
    missing = df.isnull().sum()
    total = max(1, len(df))
    
    result = pd.DataFrame({
        "column": missing.index,
        "missing_count": missing.values,
        "missing_pct": (missing.values / total * 100).round(2)
    })
    
    result = result[result["missing_count"] > 0]
    return result.sort_values("missing_count", ascending=False).reset_index(drop=True)


# ============================================================================
# GROUPING & AGGREGATION
# ============================================================================

def top_n_per_group(df: pd.DataFrame, group_by_column: str, metric_column: str, n: int = 5, ascending: bool = False) -> pd.DataFrame:
    """Returns the top or bottom N rows for each group based on a metric.
    
    Args:
        group_by_column: Grouping column
        metric_column: Numeric column to rank by
        n: Number of rows per group
        ascending: False for top N (highest values), True for bottom N (lowest values)
    
    Returns:
        DataFrame with top/bottom N rows per group
    
    Example:
        >>> top_n_per_group(df, "region", "revenue", n=3, ascending=False)
        # Returns the 3 highest-revenue transactions per region
    """
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


def group_statistics(
    df: pd.DataFrame,
    group_by_column: str,
    value_column: str,
    stats: Optional[List[str]] = None
) -> pd.DataFrame:
    """Compute multiple statistics per group in one operation.
    
    Args:
        group_by_column: Column to group by
        value_column: Numeric column to analyze
        stats: List of statistics (default: ["mean", "sum", "count", "min", "max", "std"])
    
    Returns:
        DataFrame with one row per group and columns for each statistic
        Sorted by sum descending
    
    Example:
        >>> group_statistics(df, "region", "revenue", stats=["sum", "mean", "count"])
        # Returns sum, mean, and count of revenue per region
    """
    _require_columns(df, group_by_column, value_column)
    
    if stats is None:
        stats = ["mean", "sum", "count", "min", "max", "std"]
    
    # Validate stats
    valid_stats = {"mean", "sum", "count", "min", "max", "std", "median", "var"}
    invalid = [s for s in stats if s not in valid_stats]
    if invalid:
        raise ToolkitError(f"Invalid statistics: {', '.join(invalid)}. Use: {', '.join(sorted(valid_stats))}")
    
    df2 = df[[group_by_column, value_column]].copy()
    df2[value_column] = safe_numeric_cast(df2[value_column])
    
    result = df2.groupby(group_by_column, dropna=False)[value_column].agg(stats).reset_index()
    
    # Sort by sum if available, otherwise by first stat
    sort_col = "sum" if "sum" in stats else stats[0]
    return result.sort_values(by=sort_col, ascending=False).reset_index(drop=True)


# ============================================================================
# PIVOTING & CROSS-TABULATION
# ============================================================================

def pivot_table(df: pd.DataFrame, index: str, columns: str, values: str, aggfunc: str = "sum") -> pd.DataFrame:
    """Create a pivot table summarizing values across two categorical dimensions.
    
    Args:
        index: Column to use as rows
        columns: Column to use as columns
        values: Numeric column to aggregate
        aggfunc: Aggregation function (sum, mean, median, count)
    
    Returns:
        Pivot table with index as rows and unique column values as columns
    
    Example:
        >>> pivot_table(df, index="region", columns="quarter", values="revenue", aggfunc="sum")
        # Shows total revenue per region per quarter
    """
    if df.empty:
        return df.copy()
    
    _require_columns(df, index, columns, values)
    
    valid_funcs = {"sum", "mean", "median", "count", "min", "max"}
    if aggfunc not in valid_funcs:
        raise ToolkitError(f"Invalid aggfunc: {aggfunc}. Use: {', '.join(sorted(valid_funcs))}")
    
    df2 = df.copy()
    df2[values] = safe_numeric_cast(df2[values])
    
    pivot = df2.pivot_table(index=index, columns=columns, values=values, aggfunc=aggfunc, fill_value=0)
    return pivot.reset_index()


# ============================================================================
# STATISTICAL MEASURES
# ============================================================================

def percentile(df: pd.DataFrame, column: str, p: Any) -> pd.DataFrame:
    """Calculate the p-th percentile of a numeric column.
    
    Args:
        column: Numeric column
        p: Percentile value (0-100)
    
    Returns:
        Single-row DataFrame with the percentile value
    
    Example:
        >>> percentile(df, "revenue", 95)
        # Returns the 95th percentile of revenue
    """
    _require_columns(df, column)
    
    try:
        p_float = float(p)
    except Exception:
        raise ToolkitError(f"Percentile 'p' must be a number, got: {p}")
    
    if not (0.0 <= p_float <= 100.0):
        raise ToolkitError(f"Percentile 'p' must be between 0 and 100, got: {p_float}")
    
    s = safe_numeric_cast(df[column])
    val = float(np.nanpercentile(s.to_numpy(dtype=float), p_float))
    
    col_name = f"{column}_p{int(p_float) if p_float.is_integer() else p_float}"
    return pd.DataFrame({col_name: [val]})


def outliers(df: pd.DataFrame, column: str, method: str = "iqr", k: Any = 1.5) -> pd.DataFrame:
    """Identify rows where a numeric column value is an outlier.
    
    Args:
        column: Numeric column to check
        method: Detection method ("iqr" or "zscore")
        k: Threshold multiplier (IQR: 1.5 = mild, 3.0 = extreme; Z-score: 2 or 3)
    
    Returns:
        DataFrame containing only outlier rows
    
    Example:
        >>> outliers(df, "revenue", method="iqr", k=1.5)
        # Returns rows with revenue outside Q1 - 1.5*IQR and Q3 + 1.5*IQR
    """
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
    elif method_l == "zscore":
        mu = float(np.nanmean(s.to_numpy(dtype=float)))
        sigma = float(np.nanstd(s.to_numpy(dtype=float))) or np.nan
        with np.errstate(divide="ignore", invalid="ignore"):
            z = (s - mu) / sigma
        mask = np.abs(z) > kf
    else:
        raise ToolkitError(f"Invalid method: {method}. Use 'iqr' or 'zscore'")
    
    return df[mask].reset_index(drop=True)


def correlation(
    df: pd.DataFrame,
    columns: Optional[List[str]] = None,
    method: str = "pearson"
) -> pd.DataFrame:
    """Compute pairwise correlation matrix for numeric columns.
    
    Args:
        columns: List of columns to correlate (default: all numeric)
        method: Correlation method ("pearson", "spearman", or "kendall")
    
    Returns:
        Correlation matrix with variable names as first column
    
    Example:
        >>> correlation(df, columns=["revenue", "cost", "profit"])
        # Shows correlations between these three metrics
    """
    valid_methods = {"pearson", "spearman", "kendall"}
    if method not in valid_methods:
        raise ToolkitError(f"Invalid method: {method}. Use: {', '.join(sorted(valid_methods))}")
    
    if columns:
        for col in columns:
            _require_columns(df, col)
        subset = df[columns].copy()
        for col in columns:
            subset[col] = safe_numeric_cast(subset[col])
    else:
        subset = df.select_dtypes(include=["number"])
    
    if subset.empty:
        raise ToolkitError("No numeric columns found for correlation")
    
    corr = subset.corr(method=method)
    return corr.reset_index().rename(columns={"index": "variable"})


# ============================================================================
# RANKING & BINNING
# ============================================================================

def rank_values(
    df: pd.DataFrame,
    column: str,
    method: str = "dense",
    ascending: bool = False
) -> pd.DataFrame:
    """Add a rank column based on values in the specified column.
    
    Args:
        column: Column to rank by
        method: Ranking method ("dense", "min", "max", "average", "first")
        ascending: True for low values = rank 1, False for high values = rank 1
    
    Returns:
        Original DataFrame with additional rank column
    
    Example:
        >>> rank_values(df, "revenue", method="dense", ascending=False)
        # Adds 'revenue_rank' column where highest revenue = rank 1
    """
    _require_columns(df, column)
    
    valid_methods = {"dense", "min", "max", "average", "first"}
    if method not in valid_methods:
        raise ToolkitError(f"Invalid method: {method}. Use: {', '.join(sorted(valid_methods))}")
    
    df2 = df.copy()
    df2[column] = safe_numeric_cast(df2[column])
    df2[f"{column}_rank"] = df2[column].rank(method=method, ascending=ascending)
    
    return df2.reset_index(drop=True)


def bin_values(
    df: pd.DataFrame,
    column: str,
    bins: Any = 5,
    labels: Optional[List[str]] = None
) -> pd.DataFrame:
    """Create categorical bins from a numeric column.
    
    Args:
        column: Numeric column to bin
        bins: Number of equal-width bins OR list of bin edges
        labels: Optional custom labels for bins
    
    Returns:
        Original DataFrame with additional binned column
    
    Example:
        >>> bin_values(df, "age", bins=[0, 18, 35, 50, 100], labels=["Child", "Young", "Middle", "Senior"])
        # Adds 'age_binned' column with age groups
    """
    _require_columns(df, column)
    
    df2 = df.copy()
    df2[column] = safe_numeric_cast(df2[column])
    
    try:
        df2[f"{column}_binned"] = pd.cut(df2[column], bins=bins, labels=labels)
    except Exception as e:
        raise ToolkitError(f"Binning failed: {e}")
    
    return df2.reset_index(drop=True)


# ============================================================================
# TIME SERIES & SEQUENTIAL
# ============================================================================

def rolling_aggregate(
    df: pd.DataFrame,
    value_column: str,
    window: int = 3,
    func: str = "mean",
    sort_by_column: Optional[str] = None
) -> pd.DataFrame:
    """Calculate rolling/moving aggregates (moving average, rolling sum, etc.).
    
    Args:
        value_column: Numeric column to aggregate
        window: Rolling window size (default 3)
        func: Aggregation function ("mean", "sum", "min", "max")
        sort_by_column: Optional column to sort by before computing (e.g., date)
    
    Returns:
        Original DataFrame with additional rolling aggregate column
    
    Example:
        >>> rolling_aggregate(df, "revenue", window=7, func="mean", sort_by_column="date")
        # Adds 'revenue_rolling_mean' with 7-day moving average
    """
    _require_columns(df, value_column)
    
    valid_funcs = {"mean", "sum", "min", "max"}
    if func not in valid_funcs:
        raise ToolkitError(f"Invalid func: {func}. Use: {', '.join(sorted(valid_funcs))}")
    
    df2 = df.copy()
    
    if sort_by_column:
        _require_columns(df2, sort_by_column)
        df2 = df2.sort_values(sort_by_column)
    
    df2[value_column] = safe_numeric_cast(df2[value_column])
    
    try:
        window_int = int(window)
        if window_int < 1:
            raise ValueError
    except Exception:
        raise ToolkitError(f"Window must be a positive integer, got: {window}")
    
    df2[f"{value_column}_rolling_{func}"] = df2[value_column].rolling(
        window=window_int, min_periods=1
    ).agg(func)
    
    return df2.reset_index(drop=True)


def cumulative_sum(
    df: pd.DataFrame,
    value_column: str,
    group_by_column: Optional[str] = None,
    sort_by_column: Optional[str] = None
) -> pd.DataFrame:
    """Calculate cumulative sum, optionally grouped and sorted.
    
    Args:
        value_column: Numeric column to sum
        group_by_column: Optional grouping column (e.g., "region")
        sort_by_column: Optional sort column (e.g., "date")
    
    Returns:
        Original DataFrame with additional cumulative sum column
    
    Example:
        >>> cumulative_sum(df, "revenue", group_by_column="region", sort_by_column="date")
        # Adds 'revenue_cumsum' with running total per region over time
    """
    _require_columns(df, value_column)
    
    df2 = df.copy()
    
    if sort_by_column:
        _require_columns(df2, sort_by_column)
        df2 = df2.sort_values(sort_by_column)
    
    df2[value_column] = safe_numeric_cast(df2[value_column])
    
    if group_by_column:
        _require_columns(df2, group_by_column)
        df2[f"{value_column}_cumsum"] = df2.groupby(group_by_column)[value_column].cumsum()
    else:
        df2[f"{value_column}_cumsum"] = df2[value_column].cumsum()
    
    return df2.reset_index(drop=True)


# ============================================================================
# SIMPLE AGGREGATES (No Grouping)
# ============================================================================

def sum_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Compute the total (sum) of a numeric column without grouping.
    
    Args:
        column: Numeric column to sum
    
    Returns:
        Single-row DataFrame with columns: ["metric", "value"]
    
    Example:
        >>> sum_column(df, "revenue")
        # Returns total revenue across all rows
    """
    _require_columns(df, column)
    s = safe_numeric_cast(df[column])
    total = float(np.nansum(s.to_numpy(dtype=float)))
    return pd.DataFrame({"metric": [f"Total {column}"], "value": [total]})

# TOOLS SPECIFICATION FOR GEMINI FUNCTION CALLING
# ============================================================================

TOOLS_SPEC = [
    # Legacy functions
    {
        "name": "run_aggregation",
        "description": "Group by a dimension and aggregate a numeric metric with a function (sum, mean, count, max, min)",
        "parameters": {
            "type": "object",
            "properties": {
                "dimension": {"type": "string", "description": "Column to group by"},
                "metric": {"type": "string", "description": "Numeric column to aggregate"},
                "func": {"type": "string", "enum": ["sum", "mean", "avg", "count", "max", "min"], "description": "Aggregation function"},
            },
            "required": ["dimension", "metric", "func"],
        },
        "examples": [
            "total revenue by region",
            "sum of sales per product",
            "average cost per category",
            "count orders by customer",
            "max profit per department",
            "revenue totals grouped by region"
        ],
    },
    {
        "name": "run_variance",
        "description": "Calculate difference and % change between two numeric period columns grouped by a dimension",
        "parameters": {
            "type": "object",
            "properties": {
                "dimension": {"type": "string", "description": "Group key column"},
                "period_a": {"type": "string", "description": "First period column (baseline/earlier)"},
                "period_b": {"type": "string", "description": "Second period column (comparison/later)"},
            },
            "required": ["dimension", "period_a", "period_b"],
        },
        "examples": [
            "compare 2023 vs 2024 sales",
            "year over year change in revenue",
            "difference between Q1 and Q2",
            "period over period growth by region"
        ],
    },
    {
        "name": "run_describe",
        "description": "Summarize numeric columns with count, mean, std, min, max, optionally grouped",
        "parameters": {
            "type": "object",
            "properties": {
                "include": {"type": "string", "enum": ["number", "all"], "default": "number"},
                "group_by": {"type": "string", "description": "Optional column to group by before describing"},
            },
        },
        "examples": [
            "describe dataset",
            "summary of numeric columns",
            "dataset overview",
            "overall stats",
            "basic statistics"
        ],
    },
    
    # Core data manipulation
    {
        "name": "filter_rows",
        "description": "Filter rows based on a list of conditions (AND logic across filters)",
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
        "description": "Stable sort by a column with optional limit",
        "parameters": {
            "type": "object",
            "properties": {
                "sort_by_column": {"type": "string", "description": "Column to sort by"},
                "ascending": {"type": "boolean", "default": False, "description": "True for ascending order"},
                "limit": {"type": "integer", "minimum": 0, "default": 0, "description": "Optional row limit (0=no limit)"}
            },
            "required": ["sort_by_column"]
        }
    },
    
    # Frequency & distribution
    {
        "name": "value_counts",
        "description": "Frequency table for a column with optional percentage",
        "parameters": {
            "type": "object",
            "properties": {
                "column": {"type": "string", "description": "Column to count"},
                "top": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 100, "description": "Maximum rows to return"},
                "include_pct": {"type": "boolean", "default": True, "description": "Include percentage column"}
            },
            "required": ["column"]
        },
        "examples": [
            "top categories",
            "frequency of region",
            "count of customers",
            "most common segment",
            "value distribution of status"
        ]
    },
    {
        "name": "missing_values",
        "description": "Summary of missing values per column",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    
    # Pivoting
    {
        "name": "pivot_table",
        "description": "Pivot a numeric values column across two categorical dimensions",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {"type": "string", "description": "Column for rows"},
                "columns": {"type": "string", "description": "Column for columns"},
                "values": {"type": "string", "description": "Numeric column to aggregate"},
                "aggfunc": {"type": "string", "enum": ["sum", "mean", "median", "count", "min", "max"], "default": "sum"}
            },
            "required": ["index", "columns", "values"]
        },
        "examples": [
            "revenue by region and quarter",
            "sum sales by product and month",
            "count orders per segment and channel",
            "average price by category and brand"
        ]
    },
    
    # Statistical measures
    {
        "name": "percentile",
        "description": "Compute the p-th percentile (0-100) for a numeric column",
        "parameters": {
            "type": "object",
            "properties": {
                "column": {"type": "string", "description": "Numeric column"},
                "p": {"type": "number", "minimum": 0, "maximum": 100, "description": "Percentile value (e.g., 50 for median)"}
            },
            "required": ["column", "p"]
        }
    },
    {
        "name": "outliers",
        "description": "Identify rows where a numeric column is an outlier by IQR or z-score method",
        "parameters": {
            "type": "object",
            "properties": {
                "column": {"type": "string", "description": "Numeric column to check"},
                "method": {"type": "string", "enum": ["iqr", "zscore"], "default": "iqr"},
                "k": {"type": "number", "default": 1.5, "description": "Threshold multiplier (IQR: 1.5=mild, 3.0=extreme; Z-score: 2 or 3)"}
            },
            "required": ["column"]
        }
    },
    {
        "name": "correlation",
        "description": "Compute pairwise correlation matrix for numeric columns",
        "parameters": {
            "type": "object",
            "properties": {
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of columns to correlate (default: all numeric)"
                },
                "method": {"type": "string", "enum": ["pearson", "spearman", "kendall"], "default": "pearson"}
            }
        }
    },
    
    # Ranking & binning
    {
        "name": "rank_values",
        "description": "Add a rank column based on values in a specified column",
        "parameters": {
            "type": "object",
            "properties": {
                "column": {"type": "string", "description": "Column to rank by"},
                "method": {"type": "string", "enum": ["dense", "min", "max", "average", "first"], "default": "dense"},
                "ascending": {"type": "boolean", "default": False, "description": "True for low values = rank 1"}
            },
            "required": ["column"]
        }
    },
    {
        "name": "bin_values",
        "description": "Create categorical bins from a numeric column",
        "parameters": {
            "type": "object",
            "properties": {
                "column": {"type": "string", "description": "Numeric column to bin"},
                "bins": {"description": "Number of equal-width bins OR list of bin edges"},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional custom labels for bins"
                }
            },
            "required": ["column"]
        }
    },
    
    # Time series & sequential
    {
        "name": "rolling_aggregate",
        "description": "Calculate rolling/moving aggregates (moving average, rolling sum, etc.)",
        "parameters": {
            "type": "object",
            "properties": {
                "value_column": {"type": "string", "description": "Numeric column to aggregate"},
                "window": {"type": "integer", "minimum": 1, "default": 3, "description": "Rolling window size"},
                "func": {"type": "string", "enum": ["mean", "sum", "min", "max"], "default": "mean"},
                "sort_by_column": {"type": "string", "description": "Optional column to sort by first (e.g., date)"}
            },
            "required": ["value_column"]
        }
    },
    {
        "name": "cumulative_sum",
        "description": "Calculate cumulative sum, optionally grouped and sorted",
        "parameters": {
            "type": "object",
            "properties": {
                "value_column": {"type": "string", "description": "Numeric column to sum"},
                "group_by_column": {"type": "string", "description": "Optional grouping column"},
                "sort_by_column": {"type": "string", "description": "Optional sort column (e.g., date)"}
            },
            "required": ["value_column"]
        }
    },
    
    # Simple aggregates
    {
        "name": "sum_column",
        "description": "Compute the total (sum) of a numeric column without grouping",
        "parameters": {
            "type": "object",
            "properties": {
                "column": {"type": "string", "description": "Numeric column to sum"}
            },
            "required": ["column"]
        },
        "examples": [
            "sum of revenue",
            "total input",
            "add up all sales",
            "grand total of cost",
            "what is the total amount"
        ]
    },
]