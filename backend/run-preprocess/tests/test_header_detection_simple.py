import pandas as pd

try:
    from ..header_utils import detect_header_row_simple, finalize_headers, build_analysis_hints  # type: ignore
except Exception:  # pragma: no cover
    from header_utils import detect_header_row_simple, finalize_headers, build_analysis_hints  # type: ignore


def test_detect_header_with_title_rows():
    rows = [
        ["Consolidated Balance Sheet", "", ""],
        ["Metric", "2023", "2024"],
        ["Cash & Equivalents", "1990", "3389"],
        ["Short-Term Investments", "19218", "9907"],
    ]
    df = pd.DataFrame(rows)
    idx, conf = detect_header_row_simple(df, lookahead=5)
    assert idx == 1
    assert conf >= 0.3
    raw_headers = df.iloc[idx].tolist()
    final_headers, issues = finalize_headers(raw_headers)
    assert final_headers[0].lower().startswith("metric")
    data = df.iloc[idx + 1 :].reset_index(drop=True).copy()
    data.columns = final_headers
    hints, summary = build_analysis_hints(data, final_headers, idx, conf)
    assert isinstance(hints, dict)
    assert summary and "Header row" in summary or "Header row" in summary.capitalize()


def test_negative_numeric_row_not_header():
    rows = [
        ["100", "200", "300"],
        ["Name", "Value", "Score"],
        ["A", "1", "2"],
        ["B", "3", "4"],
    ]
    df = pd.DataFrame(rows)
    idx, conf = detect_header_row_simple(df, lookahead=4)
    assert idx == 1  # should prefer the textual header row
    assert conf > 0.3
