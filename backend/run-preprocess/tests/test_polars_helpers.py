import polars as pl
import math

# Import functions under test
try:
    from ..pipeline_adapter_polars import _drop_fully_blank_rows_pl, _detect_header_row_pl, _numeric_expr_for, NULL_TOKENS
except Exception:  # fallback for direct invocation
    from pipeline_adapter_polars import _drop_fully_blank_rows_pl, _detect_header_row_pl, _numeric_expr_for, NULL_TOKENS  # type: ignore


def test_drop_fully_blank_rows_pl():
    df = pl.DataFrame({
        "a": [None, " ", "value", None],
        "b": [None, "\t", "123", "-"],
    })
    # '-' is a NULL_TOKEN per shared constants
    cleaned = _drop_fully_blank_rows_pl(df)
    # Expect rows with any non-null/non-null-token value to remain
    # Row 0: all null -> drop
    # Row 1: whitespace only -> drop
    # Row 2: has values -> keep
    # Row 3: a=None, b='-' (null token) -> drop
    assert cleaned.height == 1
    assert cleaned.select(pl.first()).to_series()[0] == "value"


def test_detect_header_row_pl():
    # First row looks like header (alpha), second more numeric
    df = pl.DataFrame({
        "c0": ["Product", "A", "B"],
        "c1": ["Revenue", "100", "200"],
        "c2": ["Qty", "1", "3"],
    })
    # The adapter reads CSVs without header; emulate that by providing rows as values
    # Here, row 0 is header-like
    row_like = pl.DataFrame(
        [df.select("c0").to_series(), df.select("c1").to_series(), df.select("c2").to_series()],
    ).transpose(include_header=False)
    hdr_row = _detect_header_row_pl(row_like)
    assert hdr_row == 0


def test_numeric_expr_for_parsing():
    df = pl.DataFrame({
        "x": [
            "1,234",        # separators
            "(12.5)",       # parens negative
            "50%",          # percent
            "$3,000",       # currency
            "1.2k",         # K suffix
            "-",            # null token -> None
            None,
        ]
    })
    expr = _numeric_expr_for("x").alias("y")
    out = df.select(expr)
    got = out["y"].to_list()

    assert got[0] == 1234.0
    assert math.isclose(got[1], -12.5)
    assert math.isclose(got[2], 0.5)
    assert got[3] == 3000.0
    assert math.isclose(got[4], 1200.0)
    assert got[5] is None
    assert got[6] is None
