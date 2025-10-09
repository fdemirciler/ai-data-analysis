import pytest

# Temporarily add the parent directory to the path to allow imports
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now, import the module
import aliases

# Sample column list for testing
COLUMN_NAMES = ["revenue", "revenue_diff", "quantity", "category", "department", "Customer Name"]

# Test cases for resolve_column, covering all logic paths
@pytest.mark.parametrize("alias, column_names, expected", [
    # 1. Exact matches
    ("revenue", COLUMN_NAMES, "revenue"),
    ("Customer Name", COLUMN_NAMES, "Customer Name"),

    # 2. Alias matches (from ALIASES dict)
    ("sales", COLUMN_NAMES, "revenue"),       # ALIASES["sales"] -> "revenue"
    ("rev", COLUMN_NAMES, "revenue"),         # ALIASES["rev"] -> "revenue"
    ("profit", COLUMN_NAMES, "revenue_diff"), # ALIASES["profit"] -> "revenue_diff"
    ("qty", COLUMN_NAMES, "quantity"),        # ALIASES["qty"] -> "quantity"
    ("cat", COLUMN_NAMES, "category"),        # ALIASES["cat"] -> "category"

    # 3. Fuzzy matches (using difflib with cutoff=0.8)
    ("revnue", COLUMN_NAMES, "revenue"),      # Typo, high similarity
    ("departmen", COLUMN_NAMES, "department"),# Typo, high similarity
    ("Cstomer Name", COLUMN_NAMES, "Customer Name"), # Typo, high similarity

    # 4. No match scenarios
    ("Customer", COLUMN_NAMES, None),             # Partial word, similarity is too low for the 0.8 cutoff
    ("nonexistent", COLUMN_NAMES, None),          # No possible match
    ("sales", ["col1", "col2"], None),             # Alias exists, but its target ("revenue") is not in the column list

    # 5. Edge cases
    (None, COLUMN_NAMES, None),                   # None input
    ("revenue", [], None),                         # Empty column list
])
def test_resolve_column(alias, column_names, expected, monkeypatch):
    """
    Tests the resolve_column function with various aliases, column lists, and scenarios.
    """
    # Ensure the ALIASES dict is consistent for this test
    test_aliases = {
        "profit": "revenue_diff",
        "sales": "revenue",
        "rev": "revenue",
        "qty": "quantity",
        "count": "quantity",
        "cat": "category",
        "dept": "department",
        "seg": "segment",
    }
    monkeypatch.setattr(aliases, "ALIASES", test_aliases)
    assert aliases.resolve_column(alias, column_names) == expected