from pathlib import Path

import os

try:
    from ..pipeline_adapter_polars import process_file_to_artifacts  # type: ignore
except Exception:  # pragma: no cover
    from pipeline_adapter_polars import process_file_to_artifacts  # type: ignore


def test_polars_integration_balance_sheet(tmp_path):
    # Ensure lookahead default is present for deterministic behavior
    os.environ.setdefault("PREPROCESS_HEADER_LOOKAHEAD", "12")

    # Locate fixture next to this test
    csv_path = Path(__file__).resolve().parent / "fixtures" / "balance_sheet.csv"
    assert csv_path.exists(), f"fixture missing: {csv_path}"

    result = process_file_to_artifacts(str(csv_path))
    payload = result.payload

    # v2 fields present
    assert payload.get("schema_version") == "2.0"
    header_info = payload.get("header_info") or {}
    hints = payload.get("analysis_hints") or {}
    assert isinstance(header_info, dict) and isinstance(hints, dict)

    # Header detection: expect row 1 (0-based) due to title row at 0
    assert header_info.get("header_row_index") == 1
    conf = float(header_info.get("confidence") or 0.0)
    assert 0.0 <= conf <= 1.0

    final_headers = header_info.get("final_headers") or []
    assert isinstance(final_headers, list) and len(final_headers) >= 2
    assert str(final_headers[0]).lower() in ("item", "metric")

    # Hints sanity
    assert isinstance(hints.get("numeric_columns"), list)
    assert isinstance(hints.get("temporal_columns"), list)
    assert hints.get("first_column_type") in ("dimension", "data")
    # Balance sheet-like: first column is label/dimension, many numeric columns
    assert hints.get("likely_pivoted") in (True, False)  # don't force value, just ensure present
