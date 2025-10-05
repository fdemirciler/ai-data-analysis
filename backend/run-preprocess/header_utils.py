"""
Header detection and metadata helpers (simple, pragmatic).

Provides:
- detect_header_row_simple(df, lookahead=12) -> (idx, confidence)
- finalize_headers(raw_headers) -> (final_headers, issues)
- build_analysis_hints(df_after_header, final_headers, header_row_index, confidence) -> (hints, dataset_summary)

Design goals:
- Minimal signals: alpha_ratio, non_empty_ratio, distinctness, next_row_numeric.
- Year-like used only as a tie-breaker.
- Confidence normalized to 0..1 (average of signals).
- Keep payload lightweight; no per-signal dumps in payload.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

import pandas as pd
from pandas.api import types as ptypes

YEAR_RE = re.compile(r"^(19|20)\d{2}$")
CURRENCY_PREFIX_RE = re.compile(r"^[\$€£¥]")
GENERIC_COL_RE = re.compile(r"^(col|column|unnamed)_?\d*$", re.IGNORECASE)


def _is_empty_token(s: str) -> bool:
    if s is None:
        return True
    s2 = str(s).strip().lower()
    return s2 in ("", "none", "nan", "null", "unnamed")


def is_numeric_string(s: str) -> bool:
    if s is None:
        return False
    t = str(s).strip()
    if t == "":
        return False
    # Tolerate commas, currency symbols, parentheses, percent
    t = (
        t.replace(",", "")
        .replace("(", "-")
        .replace(")", "")
        .replace("%", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("¥", "")
    )
    try:
        float(t)
        return True
    except Exception:
        return False


def _row_metrics(vals: List[str]) -> Tuple[float, float, float]:
    # alpha_ratio, distinctness, non_empty_ratio (returned separately for clarity)
    if not vals:
        return 0.0, 0.0, 0.0
    non_empty = [v for v in vals if v != ""]
    if not non_empty:
        return 0.0, 0.0, 0.0
    alpha_ratio = sum(1 for v in non_empty if re.search(r"[A-Za-z]", v)) / len(non_empty)
    distinctness = len(set(non_empty)) / len(non_empty)
    non_empty_ratio = len(non_empty) / max(1, len(vals))
    return float(alpha_ratio), float(distinctness), float(non_empty_ratio)


def detect_header_row_simple(df: pd.DataFrame, lookahead: int = 12) -> Tuple[int, float]:
    """Return (best_row_index, confidence) using 4 simple signals.

    Signals per candidate row r (first `lookahead` rows):
    - alpha_ratio: share of non-empty cells containing letters
    - non_empty_ratio: share of non-empty cells
    - distinctness: unique/total among non-empty
    - next_row_numeric: share of non-empty cells in row r+1 that are numeric-like

    Score is the average of the four signals (0..1). Year-like content is used
    only as a tie-breaker when scores are nearly equal.
    """
    max_r = min(len(df), max(1, lookahead))
    best_idx = 0
    best_eff_score = -1.0
    best_conf_score = 0.0
    best_year_ratio = -1.0

    lower_empty_tokens = {"", "none", "nan", "null"}
    for r in range(max_r):
        # fillna before string cast to avoid literal 'None'
        row = df.iloc[r].fillna("").astype(str).str.strip()
        vals_raw = row.tolist()
        vals = ["" if str(v).strip().lower() in lower_empty_tokens else str(v).strip() for v in vals_raw]
        alpha_ratio, distinctness, non_empty_ratio = _row_metrics(vals)
        non_empty_count = sum(1 for v in vals if v != "")
        if non_empty_ratio < 0.5 or non_empty_count < 2:
            continue  # skip mostly empty rows

        next_row_numeric = 0.0
        if r + 1 < len(df):
            nxt = df.iloc[r + 1].fillna("").astype(str).str.strip()
            nxt_vals = [x for x in nxt.tolist() if str(x).strip().lower() not in lower_empty_tokens]
            if nxt_vals:
                next_row_numeric = sum(1 for v in nxt_vals if is_numeric_string(v)) / len(nxt_vals)

        score_raw = (alpha_ratio + non_empty_ratio + distinctness + next_row_numeric) / 4.0

        # Heuristic boost/penalty layer (does not affect confidence, only selection)
        ne = [v for v in vals if v != ""]
        year_like_ratio = 0.0
        if ne:
            year_like_ratio = sum(1 for v in ne if YEAR_RE.match(v)) / len(ne)

        # Prefer a year-header pattern: majority of columns from col1 are years,
        # and the first column is empty or non-numeric (dimension/title)
        from_c1 = [v for v in vals[1:] if v != ""] if len(vals) > 1 else []
        year_like_from_c1 = 0.0
        if from_c1:
            year_like_from_c1 = sum(1 for v in from_c1 if YEAR_RE.match(v)) / len(from_c1)
        first_tok = vals[0] if vals else ""
        first_tok_numeric = is_numeric_string(first_tok)
        year_header_candidate = bool(year_like_from_c1 >= 0.6 and (first_tok == "" or not first_tok_numeric))

        # Penalize currency-like data rows: many columns look like currency values
        currency_ratio_from_c1 = 0.0
        if from_c1:
            currency_ratio_from_c1 = sum(1 for v in from_c1 if CURRENCY_PREFIX_RE.match(v)) / len(from_c1)
        currency_row_candidate = bool(currency_ratio_from_c1 >= 0.5 and first_tok != "")

        boost = 0.4 if year_header_candidate else 0.0
        penalty = 0.4 if currency_row_candidate else 0.0
        score_eff = max(0.0, min(1.0, score_raw + boost - penalty))

        # Selection uses effective score; confidence remains based on raw score
        if score_eff > best_eff_score:
            best_idx, best_eff_score, best_conf_score, best_year_ratio = r, score_eff, score_raw, year_like_ratio
        elif abs(score_eff - best_eff_score) <= 0.02 and year_like_ratio > best_year_ratio:
            best_idx, best_eff_score, best_conf_score, best_year_ratio = r, score_eff, score_raw, year_like_ratio

        # End candidate loop

    confidence = max(0.0, min(1.0, float(best_conf_score if best_eff_score >= 0.0 else 0.0)))
    return int(best_idx), float(confidence)


def finalize_headers(raw_headers: List[Any]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Replace empty/generic with col_i, ensure uniqueness, return issues list.
    Issues only for replacements of empty/generic headers.
    """
    final: List[str] = []
    issues: List[Dict[str, Any]] = []
    for i, h in enumerate(raw_headers):
        s = None if h is None else str(h).strip()
        if not s or _is_empty_token(s) or GENERIC_COL_RE.match(s):
            assigned = f"col_{i+1}"
            issues.append({"col_index": i, "reason": "empty_or_generic_header", "original": h, "assigned": assigned})
            final.append(assigned)
        else:
            final.append(s)

    # enforce uniqueness with suffixes
    seen: Dict[str, int] = {}
    uniq: List[str] = []
    for h in final:
        cnt = seen.get(h, 0)
        if cnt == 0:
            uniq.append(h)
        else:
            uniq.append(f"{h}_{cnt+1}")
        seen[h] = cnt + 1
    return uniq, issues


def _is_year_or_numeric_header(h: Any) -> bool:
    if h is None:
        return False
    s = str(h).strip()
    if s == "" or _is_empty_token(s):
        return False
    return bool(YEAR_RE.match(s) or is_numeric_string(s))


def build_analysis_hints(
    df: pd.DataFrame,
    final_headers: List[str],
    header_row_index: int,
    confidence: float,
) -> Tuple[Dict[str, Any], str]:
    """Compute compact analysis hints and a one-liner summary.

    - df: cleaned DataFrame with final headers already assigned
    """
    n_rows, n_cols = df.shape
    total_cells = max(1, n_rows * max(1, n_cols))
    n_missing_total = int(df.isna().sum().sum())
    pct_missing_total = float(n_missing_total / total_cells)

    # numeric columns by dtype or convertible ratio > 0.6
    numeric_columns: List[int] = []
    for i, c in enumerate(df.columns):
        ser = df[c]
        is_num = ptypes.is_numeric_dtype(ser)
        if not is_num:
            sample = ser.dropna().astype(str).head(50)
            if not sample.empty:
                ratio = sample.apply(is_numeric_string).mean()
                is_num = bool(ratio and float(ratio) > 0.6)
        if is_num:
            numeric_columns.append(i)

    # temporal columns: header name year-like or series parseable ratio > 0.6
    temporal_columns: List[int] = []
    for i, name in enumerate(final_headers[: len(df.columns)]):
        is_temporal = bool(YEAR_RE.match(str(name)))
        if not is_temporal:
            ser = df.iloc[:, i]
            try:
                parsed = pd.to_datetime(ser.dropna().astype(str).head(50), errors="coerce")
                if not parsed.empty and parsed.notna().mean() > 0.6:
                    is_temporal = True
            except Exception:
                is_temporal = False
        if is_temporal:
            temporal_columns.append(i)

    # first column type heuristic
    first_column_type = "data"
    if n_cols > 0:
        first_ser = df.iloc[:, 0]
        first_is_textual = not ptypes.is_numeric_dtype(first_ser)
        numeric_others = [i for i in range(1, n_cols) if i in numeric_columns]
        if first_is_textual and len(numeric_others) >= max(1, int(0.5 * max(0, n_cols - 1))):
            first_column_type = "dimension"

    likely_pivoted = bool(first_column_type == "dimension" and len(numeric_columns) >= max(1, int(0.5 * max(0, n_cols - 1))))

    hints: Dict[str, Any] = {
        "detected_header_row": int(header_row_index),
        "header_confidence": float(confidence),
        "pct_missing_total": float(pct_missing_total),
        "first_column_type": first_column_type,
        "likely_pivoted": likely_pivoted,
        "temporal_columns": temporal_columns,
        "numeric_columns": numeric_columns,
    }

    # concise summary
    dataset_summary = (
        f"Dataset has {n_rows} rows and {n_cols} columns. "
        f"Header row {header_row_index} detected (confidence {confidence:.2f}). "
        f"Structure: first column {first_column_type}, pivoted={likely_pivoted}."
    )

    return hints, dataset_summary
