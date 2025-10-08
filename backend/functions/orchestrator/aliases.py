"""
Column alias resolution utilities for classifier robustness.
"""
from __future__ import annotations

from typing import Dict, Iterable
import difflib

# Lightweight alias dictionary; extend as needed
ALIASES: Dict[str, str] = {
    # business metrics
    "profit": "revenue_diff",
    "sales": "revenue",
    "rev": "revenue",
    "qty": "quantity",
    "count": "quantity",
    # dimensions
    "cat": "category",
    "dept": "department",
    "seg": "segment",
}


def resolve_column(name: str, columns: Iterable[str]) -> str | None:
    """Resolve a user-provided or aliased column name to the actual dataset column.

    Attempts exact match, alias map, then fuzzy match using difflib.
    Returns the best guess or None if resolution fails.
    """
    cols = list(columns)
    if not name:
        return None
    # exact
    if name in cols:
        return name
    # alias
    alias = ALIASES.get(name.lower())
    if alias and alias in cols:
        return alias
    # fuzzy
    m = difflib.get_close_matches(name, cols, n=1, cutoff=0.8)
    if m:
        return m[0]
    return None
