"""
Polars-backed adapter for the preprocess service.

CSV paths use Polars for faster load and normalization, then convert to pandas
for payload construction that reuses pandas-based helpers (type inference).
Excel remains handled by pandas for compatibility.
"""
from __future__ import annotations

import io
import re
import math
from typing import Any, Dict, List, Optional

import polars as pl  # type: ignore
import pandas as pd
import os

# Reuse shared types and helpers with robust import (package/script modes)
try:
    from .pipeline_adapter import (  # type: ignore
        ProcessResult,
        NULL_TOKENS,
        KMB_PATTERN,
        CURRENCY_PATTERN,
        PARENS_PATTERN,
        PERCENT_PATTERN,
        infer_column_type,
    )
except Exception:  # pragma: no cover
    from pipeline_adapter import (  # type: ignore
        ProcessResult,
        NULL_TOKENS,
        KMB_PATTERN,
        CURRENCY_PATTERN,
        PARENS_PATTERN,
        PERCENT_PATTERN,
        infer_column_type,
    )


def _pl_read_csv(source: Any) -> pl.DataFrame:
    """Read CSV via Polars with no header (robust settings)."""
    return pl.read_csv(
        source,
        has_header=False,
        infer_schema_length=2048,
        ignore_errors=True,
        try_parse_dates=False,
    )


def _drop_fully_blank_rows_pl(df: pl.DataFrame) -> pl.DataFrame:
    cols = df.columns
    blank_exprs = []
    for c in cols:
        s = pl.col(c).cast(pl.Utf8).str.strip_chars().str.to_lowercase()
        blank_exprs.append(pl.col(c).is_null() | s.is_in(list(NULL_TOKENS)))
    all_blank = pl.all_horizontal(blank_exprs)
    return df.filter(~all_blank)


def _detect_header_row_pl(df: pl.DataFrame, lookahead: int = 5) -> int:
    max_r = min(df.height, lookahead)
    best_row = 0
    best_score = float("-inf")
    for r in range(max_r):
        row = df.row(r)
        vals = [str(v).strip() for v in row]
        non_empty_ratio = sum(1 for v in vals if v != "") / max(1, len(vals))
        alpha_ratio = sum(1 for v in vals if re.search(r"[A-Za-z]", v or "")) / max(1, len(vals))
        score = alpha_ratio - (0.5 if non_empty_ratio < 0.7 else 0)
        if score > best_score:
            best_score = score
            best_row = r
    return best_row


def _build_headers(vals: list[str]) -> list[str]:
    headers: list[str] = []
    for v in vals:
        s = re.sub(r"\s+", " ", str(v).strip())
        headers.append(s if s else "Column")
    seen: Dict[str, int] = {}
    dedup: list[str] = []
    for h in headers:
        n = h
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"
        else:
            seen[n] = 1
        dedup.append(n)
    return dedup


def _numeric_expr_for(col: str) -> pl.Expr:
    s = pl.col(col).cast(pl.Utf8)
    s = s.str.replace("\u2212", "-")
    s = s.str.replace("\u00a0", " ")
    s = s.str.replace(r"[\u2000-\u200B]", " ", literal=False)
    s = s.str.strip_chars()

    lower = s.str.to_lowercase()
    s = pl.when(lower.is_in(list(NULL_TOKENS))).then(None).otherwise(s)

    # Detect negatives via parentheses, then drop parentheses for casting
    mask_paren = s.str.contains(PARENS_PATTERN.pattern, literal=False)
    s = s.str.replace_all(r"[()]", "", literal=False)
    mask_trail = s.str.ends_with("-")
    s = s.str.replace(r"-$", "", literal=False)

    # K/M/B
    suffix = s.str.extract(KMB_PATTERN.pattern, group_index=1)
    mult = (
        pl.when(suffix.str.to_lowercase() == "k").then(1e3)
        .when(suffix.str.to_lowercase() == "m").then(1e6)
        .when(suffix.str.to_lowercase() == "b").then(1e9)
        .otherwise(1.0)
    )
    s = s.str.replace(KMB_PATTERN.pattern, "", literal=False)

    # Currency and separators
    s = s.str.replace(CURRENCY_PATTERN.pattern, "", literal=False)
    s = s.str.replace(",", "")
    s = s.str.replace(" ", "")

    # Percent
    percent_mask = s.str.contains(PERCENT_PATTERN.pattern, literal=False)
    s = s.str.replace(PERCENT_PATTERN.pattern, "", literal=False)

    nums = s.cast(pl.Float64, strict=False) * mult
    nums = pl.when(mask_paren | mask_trail).then(-nums).otherwise(nums)
    nums = pl.when(percent_mask).then(nums / 100.0).otherwise(nums)
    return nums


def _apply_numeric_normalization(df: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    numeric_cols: list[str] = []
    out = df
    for c in df.columns:
        expr = _numeric_expr_for(c)
        ratio = out.select(expr.is_not_null().mean()).item()
        if ratio is not None and float(ratio) >= 0.6:
            out = out.with_columns(expr.alias(c))
            numeric_cols.append(c)
    return out, numeric_cols


def process_file_to_artifacts(
    local_path: str,
    *,
    sample_rows_for_llm: int = 50,
    metric_rename_heuristic: bool = False,
    header_row_override: Optional[int] = None,
) -> ProcessResult:
    # Decide file kind by extension
    ext = local_path.lower().rsplit(".", 1)[-1]
    if ext in ("xlsx", "xls"):
        # Excel via pandas
        raw_df = pd.read_excel(local_path, sheet_name=0, header=None, dtype=object)
        file_kind = "excel"
    else:
        # CSV via Polars → native cleaning → convert to pandas for payload
        df_pl = _pl_read_csv(local_path)
        rows_before = df_pl.height
        work = _drop_fully_blank_rows_pl(df_pl)
        # Lazy import header helpers (package/script modes)
        try:
            from .header_utils import (
                detect_header_row_simple,
                finalize_headers,
                build_analysis_hints,
                is_numeric_string,
            )  # type: ignore
        except Exception:  # pragma: no cover
            from header_utils import (
                detect_header_row_simple,
                finalize_headers,
                build_analysis_hints,
                is_numeric_string,
            )  # type: ignore

        if header_row_override is not None:
            hdr_row = int(header_row_override)
            header_confidence = 1.0
            method = "override"
        else:
            lookahead = int(os.getenv("PREPROCESS_HEADER_LOOKAHEAD", "12"))
            pdf = work.head(lookahead).to_pandas()
            hdr_row, header_confidence = detect_header_row_simple(pdf, lookahead=lookahead)
            method = "auto_detected"

        raw_headers = [str(x) for x in work.row(hdr_row)] if work.height > hdr_row else [None] * work.width
        headers, header_issues = finalize_headers(raw_headers)
        body = work.slice(hdr_row + 1)
        # Rename first N columns to headers
        rename_map = {old: headers[i] for i, old in enumerate(body.columns[: len(headers)])}
        body = body.rename(rename_map)
        # Remove repeated header rows
        eq_exprs = [(pl.col(h).cast(pl.Utf8).str.strip_chars() == headers[i]) for i, h in enumerate(headers)]
        is_hdr_row = pl.all_horizontal(eq_exprs)
        body = body.filter(~is_hdr_row)
        # Numeric normalization
        body, numeric_cols = _apply_numeric_normalization(body)
        # Convert to pandas for payload/type inference
        df = body.to_pandas()
        # Build payload pieces
        columns_meta: Dict[str, Any] = {}
        for col in df.columns:
            col_type, dt_fmt = infer_column_type(df[col], str(col))
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
                if isinstance(v, (float, int)):
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
            columns_meta[str(col)] = entry

        # Heuristic for potential dimension
        if len(df.columns) > 0:
            first = str(df.columns[0])
            first_type = columns_meta[first]["type"]
            numeric_others = [c for c in list(df.columns)[1:] if columns_meta[str(c)]["type"] in ("integer", "float", "percentage", "currency")]
            if first_type in ("categorical", "text") and len(numeric_others) >= max(1, int(0.5 * (len(df.columns) - 1))):
                columns_meta[first]["is_potential_dimension"] = True

        dataset_meta = {
            "rows": int(df.shape[0]),
            "columns": int(df.shape[1]),
            "column_names": [str(x) for x in df.columns.tolist()],
            "dtypes": {str(c): str(df[c].dtype) for c in df.columns},
        }

        n = min(sample_rows_for_llm, len(df))
        sample = df.sample(n=n, random_state=42) if n > 0 else df.head(0)
        sample_rows: list[dict] = []
        for _, r in sample.iterrows():
            obj: Dict[str, Any] = {}
            for k, v in r.to_dict().items():
                if isinstance(v, str) and len(v) > 300:
                    obj[str(k)] = v[:300]
                elif isinstance(v, (float, int)):
                    obj[str(k)] = float(v)
                else:
                    obj[str(k)] = v if (v is None or isinstance(v, (str, int, float, bool))) else str(v)
            sample_rows.append(obj)

        # Build v2 analysis hints and dataset summary
        hints, dataset_summary = build_analysis_hints(df, headers, hdr_row, float(header_confidence))
        # Minimal header_info with transposed signal
        is_transposed = False
        non_empty_final = [h for h in headers if str(h).strip() != ""]
        if non_empty_final:
            is_transposed = all(is_numeric_string(h) for h in non_empty_final)

        header_info = {
            "method": method,
            "header_row_index": int(hdr_row),
            "confidence": float(header_confidence),
            "original_headers": [str(x) if x is not None else None for x in raw_headers],
            "final_headers": headers,
            "is_transposed": bool(is_transposed),
        }
        if header_issues:
            header_info["issues"] = header_issues

        payload: Dict[str, Any] = {
            "dataset": dataset_meta,
            "columns": columns_meta,
            "sample_rows": sample_rows,
            "cleaning_report": {
                "header_row": int(hdr_row),
                "renamed_columns": {},
                "numeric_columns": numeric_cols,
                "rows_before": int(rows_before),
                "rows_after": int(df.shape[0]),
                "file_kind": "csv",
            },
            "mode": "full",
            "version": "1",
            # v2 additive fields
            "schema_version": "2.0",
            "header_info": header_info,
            "analysis_hints": hints,
            "dataset_summary": dataset_summary,
        }

        return ProcessResult(
            cleaned_df=df,
            payload=payload,
            cleaning_report=payload["cleaning_report"],
            rows=int(df.shape[0]),
            columns=int(df.shape[1]),
        )


def process_bytes_to_artifacts(
    data: bytes,
    kind: str,
    *,
    sample_rows_for_llm: int = 50,
    metric_rename_heuristic: bool = False,
    header_row_override: Optional[int] = None,
) -> ProcessResult:
    if kind not in ("csv", "excel"):
        raise ValueError("kind must be 'csv' or 'excel'")

    if kind == "excel":
        # Excel via pandas
        raw_df = pd.read_excel(io.BytesIO(data), sheet_name=0, header=None, dtype=object)
        # Defer to shared pandas path by converting directly
        # Import locally to avoid circulars
        try:
            from .pipeline_adapter import process_df_to_artifacts as _p  # type: ignore
        except Exception:
            from pipeline_adapter import process_df_to_artifacts as _p  # type: ignore
        return _p(raw_df, "excel", sample_rows_for_llm=sample_rows_for_llm, metric_rename_heuristic=metric_rename_heuristic, header_row_override=header_row_override)
    else:
        # CSV via Polars (same as file path case)
        tmp_path = io.BytesIO(data)
        df_pl = _pl_read_csv(tmp_path)
        rows_before = df_pl.height
        work = _drop_fully_blank_rows_pl(df_pl)
        # Lazy import header helpers
        try:
            from .header_utils import (
                detect_header_row_simple,
                finalize_headers,
                build_analysis_hints,
                is_numeric_string,
            )  # type: ignore
        except Exception:  # pragma: no cover
            from header_utils import (
                detect_header_row_simple,
                finalize_headers,
                build_analysis_hints,
                is_numeric_string,
            )  # type: ignore

        if header_row_override is not None:
            hdr_row = int(header_row_override)
            header_confidence = 1.0
            method = "override"
        else:
            lookahead = int(os.getenv("PREPROCESS_HEADER_LOOKAHEAD", "12"))
            pdf = work.head(lookahead).to_pandas()
            hdr_row, header_confidence = detect_header_row_simple(pdf, lookahead=lookahead)
            method = "auto_detected"

        raw_headers = [str(x) for x in work.row(hdr_row)] if work.height > hdr_row else [None] * work.width
        headers, header_issues = finalize_headers(raw_headers)
        body = work.slice(hdr_row + 1)
        rename_map = {old: headers[i] for i, old in enumerate(body.columns[: len(headers)])}
        body = body.rename(rename_map)
        eq_exprs = [(pl.col(h).cast(pl.Utf8).str.strip_chars() == headers[i]) for i, h in enumerate(headers)]
        is_hdr_row = pl.all_horizontal(eq_exprs)
        body = body.filter(~is_hdr_row)
        body, numeric_cols = _apply_numeric_normalization(body)
        df = body.to_pandas()

        columns_meta: Dict[str, Any] = {}
        for col in df.columns:
            col_type, dt_fmt = infer_column_type(df[col], str(col))
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
                if isinstance(v, (float, int)):
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
            columns_meta[str(col)] = entry

        if len(df.columns) > 0:
            first = str(df.columns[0])
            first_type = columns_meta[first]["type"]
            numeric_others = [c for c in list(df.columns)[1:] if columns_meta[str(c)]["type"] in ("integer", "float", "percentage", "currency")]
            if first_type in ("categorical", "text") and len(numeric_others) >= max(1, int(0.5 * (len(df.columns) - 1))):
                columns_meta[first]["is_potential_dimension"] = True

        dataset_meta = {
            "rows": int(df.shape[0]),
            "columns": int(df.shape[1]),
            "column_names": [str(x) for x in df.columns.tolist()],
            "dtypes": {str(c): str(df[c].dtype) for c in df.columns},
        }
        n = min(sample_rows_for_llm, len(df))
        sample = df.sample(n=n, random_state=42) if n > 0 else df.head(0)
        sample_rows: list[dict] = []
        for _, r in sample.iterrows():
            obj: Dict[str, Any] = {}
            for k, v in r.to_dict().items():
                if isinstance(v, str) and len(v) > 300:
                    obj[str(k)] = v[:300]
                elif isinstance(v, (float, int)):
                    obj[str(k)] = float(v)
                else:
                    obj[str(k)] = v if (v is None or isinstance(v, (str, int, float, bool))) else str(v)
            sample_rows.append(obj)

        # Build v2 analysis hints and dataset summary
        hints, dataset_summary = build_analysis_hints(df, headers, hdr_row, float(header_confidence))
        # Minimal header_info with transposed signal
        is_transposed = False
        non_empty_final = [h for h in headers if str(h).strip() != ""]
        if non_empty_final:
            is_transposed = all(is_numeric_string(h) for h in non_empty_final)

        header_info = {
            "method": method,
            "header_row_index": int(hdr_row),
            "confidence": float(header_confidence),
            "original_headers": [str(x) if x is not None else None for x in raw_headers],
            "final_headers": headers,
            "is_transposed": bool(is_transposed),
        }
        if header_issues:
            header_info["issues"] = header_issues

        payload: Dict[str, Any] = {
            "dataset": dataset_meta,
            "columns": columns_meta,
            "sample_rows": sample_rows,
            "cleaning_report": {
                "header_row": int(hdr_row),
                "renamed_columns": {},
                "numeric_columns": numeric_cols,
                "rows_before": int(rows_before),
                "rows_after": int(df.shape[0]),
                "file_kind": "csv",
            },
            "mode": "full",
            "version": "1",
            # v2 additive fields
            "schema_version": "2.0",
            "header_info": header_info,
            "analysis_hints": hints,
            "dataset_summary": dataset_summary,
        }

        return ProcessResult(
            cleaned_df=df,
            payload=payload,
            cleaning_report=payload["cleaning_report"],
            rows=int(df.shape[0]),
            columns=int(df.shape[1]),
        )
