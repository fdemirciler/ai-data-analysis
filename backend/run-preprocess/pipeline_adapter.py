"""
Pipeline adapter for the preprocess service.

This module loads a raw CSV/XLSX file from a local path, performs light but
robust cleaning, infers lightweight column metadata for LLM prompting
(payload), and returns both the cleaned DataFrame and JSON-serializable
artifacts.

Design goals:
- Preserve original column names (no destructive renames).
- Excel: first sheet only.
- Deterministic sampling for payload (seed=42, up to 50 rows).
- Numeric normalization for %, K/M/B, currency symbols, and common separators.
- Add `datetime_format` where inferred with high confidence.
- Add `is_potential_dimension` instead of renaming first column to Metric.

Note: This is a focused adapter tailored for serverless preprocessing. It is
not a full port of the original repository in data_processing_profiling.md, but
it follows the same principles and payload structure agreed for this project.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# -----------------------------
# Constants & helpers
# -----------------------------

NULL_TOKENS = {
    "", "na", "n/a", "none", "null", "nil", "nan", "-", "--", "n\u00a0a",
}
KMB_PATTERN = re.compile(r"\s*([kKmMbB])\s*$")
CURRENCY_PATTERN = re.compile(r"[$€£¥]|USD|EUR|GBP|JPY|TRY|TL|₺")
TRAILING_MINUS_PATTERN = re.compile(r"-$")
PARENS_PATTERN = re.compile(r"^\(.*\)$")
PERCENT_PATTERN = re.compile(r"%")
DATE_REGEXES = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d"),
    (re.compile(r"^\d{2}/\d{2}/\d{4}$"), "%m/%d/%Y"),
    (re.compile(r"^\d{2}-\d{2}-\d{4}$"), "%m-%d-%Y"),
    (re.compile(r"^\d{2}\.\d{2}\.\d{4}$"), "%m.%d.%Y"),
    (re.compile(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$"), "%d %b %Y"),
    (re.compile(r"^[A-Za-z]{3}\s+\d{1,2},\s+\d{4}$"), "%b %d, %Y"),
]


@dataclass
class ProcessResult:
    cleaned_df: pd.DataFrame
    payload: Dict[str, Any]
    cleaning_report: Dict[str, Any]
    rows: int
    columns: int


# -----------------------------
# Loading & cleaning
# -----------------------------

def _load_raw(local_path: str) -> Tuple[pd.DataFrame, str]:
    ext = local_path.lower().rsplit(".", 1)[-1]
    if ext in ("xlsx", "xls"):
        df = pd.read_excel(local_path, sheet_name=0, header=None, dtype=object)
        kind = "excel"
    else:
        # CSV with python engine for robustness
        df = pd.read_csv(local_path, header=None, dtype=object, engine="python")
        kind = "csv"
    return df, kind


def _drop_fully_blank_rows(df: pd.DataFrame) -> pd.DataFrame:
    is_na = df.isna()
    lowered = df.astype(str).apply(lambda s: s.str.strip().str.lower(), axis=0)
    is_token_blank = lowered.isin(NULL_TOKENS)
    is_blank = is_na | is_token_blank
    keep_mask = ~is_blank.all(axis=1)
    return df.loc[keep_mask]


def _detect_header_row(df: pd.DataFrame, lookahead: int = 5) -> int:
    # Simple heuristic: choose the earliest row where more than half of columns
    # are non-numeric-ish strings, followed by a row with more numeric candidates.
    max_r = min(len(df), lookahead)
    best_row = 0
    best_score = float("-inf")
    for r in range(max_r):
        row = df.iloc[r].astype(str).str.strip()
        non_empty = row.replace({"": np.nan}).notna().mean()
        alpha_ratio = row.str.contains(r"[A-Za-z]", regex=True, na=False).mean()
        # Penalize rows with very low non-empty ratio
        score = alpha_ratio - (0.5 if non_empty < 0.7 else 0)
        if score > best_score:
            best_score = score
            best_row = r
    return best_row


def _build_headers(df: pd.DataFrame, header_row: int) -> Tuple[List[str], int]:
    row = df.iloc[header_row].tolist()
    headers: List[str] = []
    for val in row:
        s = re.sub(r"\s+", " ", str(val).strip())
        headers.append(s if s else "Column")
    # Deduplicate while preserving order
    seen = {}
    dedup: List[str] = []
    for h in headers:
        n = h
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"
        else:
            seen[n] = 1
        dedup.append(n)
    start_row = header_row + 1
    return dedup, start_row


# -----------------------------
# Numeric normalization
# -----------------------------

def _normalize_whitespace_and_minus(series: pd.Series) -> pd.Series:
    s = series.astype(str)
    s = s.str.replace("\u2212", "-", regex=False)  # unicode minus → ASCII
    s = s.str.replace("\u00a0", " ", regex=False)  # NBSP → space
    s = s.str.replace(r"[\u2000-\u200B]", " ", regex=True)  # thin spaces
    return s


def normalize_numeric_series(series: pd.Series) -> pd.Series:
    s = series.astype(object)
    s = s.where(~s.isna(), None)
    s = _normalize_whitespace_and_minus(s).str.strip()

    lower = s.str.lower()
    s = s.mask(lower.isin(NULL_TOKENS), np.nan)
    s = s.fillna("")

    # Detect negative forms and strip wrappers
    mask_paren = s.str.match(PARENS_PATTERN, na=False)
    s = s.mask(mask_paren, s.str.replace(r"^[\(](.*)[\)]$", r"\1", regex=True))
    mask_trail = s.str.endswith("-", na=False)
    s = s.mask(mask_trail, s.str[:-1])
    negative_mask = mask_paren | mask_trail

    # Extract K/M/B multiplier and strip suffix
    m = s.str.extract(KMB_PATTERN)
    suffix = m[0].fillna("") if not m.empty else ""
    mult = pd.Series(1.0, index=s.index, dtype=float)
    mult = mult.mask(suffix.str.lower() == "k", 1e3)
    mult = mult.mask(suffix.str.lower() == "m", 1e6)
    mult = mult.mask(suffix.str.lower() == "b", 1e9)
    s = s.str.replace(KMB_PATTERN.pattern, "", regex=True)

    # Strip currency and common separators
    s = s.str.replace(CURRENCY_PATTERN, "", regex=True)
    s = s.str.replace(",", "", regex=False)
    s = s.str.replace(" ", "", regex=False)

    # Percent
    percent_mask = s.str.contains(PERCENT_PATTERN, na=False)
    s = s.str.replace(PERCENT_PATTERN, "", regex=True)

    nums = pd.to_numeric(s, errors="coerce")
    nums = nums * mult
    nums = nums.mask(negative_mask, -nums)
    nums = nums.mask(percent_mask, nums / 100.0)
    nums = nums.replace([np.inf, -np.inf], np.nan)
    return nums


def is_numeric_candidate(series: pd.Series) -> bool:
    sample = series.dropna()
    if sample.empty:
        return False
    sample = sample.sample(min(100, len(sample)), random_state=42)
    parsed = normalize_numeric_series(sample)
    ratio = parsed.notna().mean()
    return ratio >= 0.6


# -----------------------------
# Type inference & utilities
# -----------------------------

def _detect_datetime_format_from_value(val: str) -> Optional[str]:
    for regex, fmt in DATE_REGEXES:
        if regex.match(val):
            return fmt
    return None


def infer_column_type(series: pd.Series, name: str) -> Tuple[str, Optional[str]]:
    """Return (type, datetime_format)."""
    s = series.dropna().astype(str).str.strip()
    if s.empty:
        return "text", None

    # Try date detection (regex + pandas parse success rate)
    sample_vals = s.sample(min(50, len(s)), random_state=42)
    regex_hits = sum(1 for v in sample_vals if _detect_datetime_format_from_value(v))
    if regex_hits / max(1, len(sample_vals)) >= 0.6:
        parsed = pd.to_datetime(s, errors="coerce")
        if parsed.notna().mean() >= 0.8:
            for v in sample_vals:
                fmt = _detect_datetime_format_from_value(v)
                if fmt:
                    return "date", fmt
            return "date", None

    # Numeric / percentage / currency
    if is_numeric_candidate(series):
        lower_name = name.lower()
        contains_pct = any("%" in str(x) for x in series.dropna().head(50))
        contains_curr = any(CURRENCY_PATTERN.search(str(x) or "") for x in series.dropna().head(50))
        if contains_pct or any(k in lower_name for k in ("percent", "pct", "rate")):
            return "percentage", None
        if contains_curr or any(k in lower_name for k in ("price", "revenue", "amount", "cost", "currency")):
            return "currency", None
        nums = normalize_numeric_series(series)
        if nums.notna().any() and (nums.dropna() % 1 == 0).mean() > 0.95:
            return "integer", None
        return "float", None

    # ID-like
    unique_ratio = series.nunique(dropna=True) / max(1, len(series.dropna()))
    lower = name.lower()
    if unique_ratio > 0.9 and any(k in lower for k in ("id", "uuid", "code", "identifier")):
        return "id", None

    # Categorical vs text
    if series.dropna().nunique() / max(1, len(series.dropna())) <= 0.2:
        return "categorical", None

    return "text", None


# -----------------------------
# Main adapter
# -----------------------------

def process_file_to_artifacts(
    local_path: str,
    *,
    sample_rows_for_llm: int = 50,
    metric_rename_heuristic: bool = False,  # kept for compatibility; not used (non-destructive)
) -> ProcessResult:
    raw_df, file_kind = _load_raw(local_path)
    rows_before = raw_df.shape[0]

    work = _drop_fully_blank_rows(raw_df).reset_index(drop=True)
    header_row = _detect_header_row(work)
    headers, start_row = _build_headers(work, header_row)

    body = work.iloc[start_row:].reset_index(drop=True)
    body.columns = headers

    # Remove rows that fully match headers (repeated header lines)
    hdr_norm = [str(h).strip() for h in headers]
    keep_mask = []
    for _, r in body.iterrows():
        vals = [str(x).strip() for x in r.tolist()]
        keep_mask.append(vals != hdr_norm)
    df = body.loc[keep_mask].reset_index(drop=True)

    # Normalize numeric columns (best-effort)
    numeric_cols: List[str] = []
    for col in df.columns:
        if is_numeric_candidate(df[col]):
            df[col] = normalize_numeric_series(df[col])
            numeric_cols.append(col)

    # Type inference & column summaries
    columns_meta: Dict[str, Any] = {}
    for col in df.columns:
        col_type, dt_fmt = infer_column_type(df[col], col)
        col_series = df[col]
        nn = col_series.dropna()
        null_pct = 0.0 if len(col_series) == 0 else (1 - len(nn) / len(col_series)) * 100.0
        unique_pct = 0.0 if len(nn) == 0 else (nn.nunique() / len(nn)) * 100.0
        vc = nn.value_counts().head(5)
        top_values = []
        for v, c in vc.items():
            val: Any = v
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                continue
            if isinstance(v, (np.floating, np.integer)):
                val = float(v)
            if isinstance(v, str) and len(v) > 300:
                val = v[:300]
            top_values.append({"value": val, "count": int(c)})

        entry: Dict[str, Any] = {
            "type": col_type,
            "null_pct": round(float(null_pct), 2),
            "unique_pct": round(float(unique_pct), 2),
            "top_values": top_values,
        }
        if col_type == "date":
            entry["datetime_format"] = dt_fmt
        entry["is_potential_dimension"] = False
        columns_meta[col] = entry

    # Heuristic for potential dimension in the first column
    if len(df.columns) > 0:
        first = df.columns[0]
        first_type = columns_meta[first]["type"]
        numeric_others = [c for c in df.columns[1:] if columns_meta[c]["type"] in ("integer", "float", "percentage", "currency")]
        if first_type in ("categorical", "text") and len(numeric_others) >= max(1, int(0.5 * (len(df.columns) - 1))):
            columns_meta[first]["is_potential_dimension"] = True

    dataset_meta = {
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "column_names": list(map(str, df.columns.tolist())),
        "dtypes": {c: str(df[c].dtype) for c in df.columns},
    }

    # Deterministic sample rows
    n = min(sample_rows_for_llm, len(df))
    sample = df.sample(n=n, random_state=42) if n > 0 else df.head(0)

    sample_rows: List[Dict[str, Any]] = []
    for _, r in sample.iterrows():
        obj = {}
        for k, v in r.to_dict().items():
            if isinstance(v, str) and len(v) > 300:
                obj[k] = v[:300]
            elif isinstance(v, (np.floating, np.integer)):
                obj[k] = float(v)
            else:
                obj[k] = v if (v is None or isinstance(v, (str, int, float, bool))) else str(v)
        sample_rows.append(obj)

    payload: Dict[str, Any] = {
        "dataset": dataset_meta,
        "columns": columns_meta,
        "sample_rows": sample_rows,
        "cleaning_report": {
            "header_row": int(header_row),
            "renamed_columns": {},
            "numeric_columns": numeric_cols,
            "rows_before": int(rows_before),
            "rows_after": int(df.shape[0]),
            "file_kind": "xlsx" if file_kind == "excel" else "csv",
        },
        "mode": "full",
        "version": "1",
    }

    if file_kind == "excel":
        payload["excelInfo"] = {"sheet_used": 0, "sheet_name": None, "sheets_total": None}

    return ProcessResult(
        cleaned_df=df,
        payload=payload,
        cleaning_report=payload["cleaning_report"],
        rows=int(df.shape[0]),
        columns=int(df.shape[1]),
    )
