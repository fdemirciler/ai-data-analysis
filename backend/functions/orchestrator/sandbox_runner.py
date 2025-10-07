"""
AST-based validation for LLM-generated analysis code.

This module statically validates dynamically generated Python analysis code to
enforce security and sandbox constraints before execution.

Checks performed:
- The presence of a required function signature: `def run(df, ctx):`
- Imports restricted to an allowlist (configurable via SANDBOX_MODE).
- Disallowed function calls (e.g., exec, open, eval).
- Disallowed attribute or name access (dunder methods, globals).
- Optional loop-depth and import-count limits (prevent runaway code).

Environment variable:
    SANDBOX_MODE = "restricted" | "rich"   (default: restricted)
"""

from __future__ import annotations
import ast
import os
from typing import Iterable, Tuple, Dict, List

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_SANDBOX_MODE = os.getenv("SANDBOX_MODE", "restricted").lower()

# Minimal baseline imports for restricted environments
ALLOWED_IMPORTS_BASE = {"pandas", "numpy", "math", "json"}

# Rich mode adds analysis and visualization support
ALLOWED_IMPORTS_RICH = {
    "matplotlib", "seaborn", "statistics", "io", "itertools", "functools",
    "collections", "re", "datetime", "base64",
}

ALLOWED_IMPORTS = set(ALLOWED_IMPORTS_BASE)
if _SANDBOX_MODE in ("rich", "extended"):
    ALLOWED_IMPORTS.update(ALLOWED_IMPORTS_RICH)

# Dangerous constructs and module prefixes
FORBIDDEN_NAMES = {"exec", "eval", "compile", "open", "__import__", "globals", "locals", "input"}

FORBIDDEN_MODULE_PREFIXES = {
    "os", "sys", "subprocess", "socket", "asyncio", "multiprocessing",
    "threading", "ctypes", "pathlib", "importlib", "pdb", "pickle",
    "dill", "requests", "urllib",
}

# Safety thresholds
MAX_IMPORTS = 12
MAX_LOOP_DEPTH = 4


# ---------------------------------------------------------------------------
# AST Validator
# ---------------------------------------------------------------------------

class _Validator(ast.NodeVisitor):
    """AST walker enforcing import, call, and naming safety rules."""

    def __init__(self, allowlist: Iterable[str]):
        super().__init__()
        self.allowlist = set(allowlist)
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.import_count = 0
        self.loop_depth = 0

    def _err(self, msg: str) -> None:
        self.errors.append(msg)

    def _warn(self, msg: str) -> None:
        self.warnings.append(msg)

    # -------------------------------
    # Import Validation
    # -------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        self.import_count += 1
        for alias in node.names:
            root = (alias.name or "").split(".")[0]
            if root not in self.allowlist:
                self._err(f"Import not allowed: {alias.name}")
            if root in FORBIDDEN_MODULE_PREFIXES:
                self._err(f"Forbidden import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.import_count += 1
        mod = node.module or ""
        root = mod.split(".")[0]
        if root not in self.allowlist:
            self._err(f"Import from not allowed: {mod}")
        if any(root == p or root.startswith(p + ".") for p in FORBIDDEN_MODULE_PREFIXES):
            self._err(f"Forbidden import from: {mod}")
        self.generic_visit(node)

    # -------------------------------
    # Function & Call Validation
    # -------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_NAMES:
            self._err(f"Forbidden call: {node.func.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self._err("Use of dunder attributes is not allowed")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__") and node.id.endswith("__"):
            self._err("Use of dunder names is not allowed")
        self.generic_visit(node)

    # -------------------------------
    # Structural Safety Checks
    # -------------------------------
    def visit_For(self, node: ast.For) -> None:
        self.loop_depth += 1
        if self.loop_depth > MAX_LOOP_DEPTH:
            self._warn(f"Deeply nested loop detected (depth {self.loop_depth})")
        self.generic_visit(node)
        self.loop_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        self.loop_depth += 1
        if self.loop_depth > MAX_LOOP_DEPTH:
            self._warn(f"Deeply nested loop detected (depth {self.loop_depth})")
        self.generic_visit(node)
        self.loop_depth -= 1


# ---------------------------------------------------------------------------
# Public Validation API
# ---------------------------------------------------------------------------

def validate_code(
    code: str,
    allowlist: Iterable[str] | None = None
) -> Tuple[bool, List[str], List[str]]:
    """
    Validate Python code against structural and security rules.

    Returns:
        (is_valid, errors, warnings)
    """
    if not code or not isinstance(code, str):
        return False, ["Empty or invalid code string."], []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"SyntaxError: {e}"], []

    # Ensure required entrypoint exists
    has_run_func = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            args = node.args.args
            if len(args) >= 2 and args[0].arg == "df" and args[1].arg == "ctx":
                has_run_func = True
                break
    if not has_run_func:
        return False, ["Missing required function: def run(df, ctx):"], []

    # Determine which allowlist to apply
    allowlist_to_use = set(allowlist) if allowlist else set(ALLOWED_IMPORTS)
    validator = _Validator(allowlist_to_use)
    validator.visit(tree)

    # Apply import/loop sanity warnings
    if validator.import_count > MAX_IMPORTS:
        validator._warn(f"Too many imports ({validator.import_count} > {MAX_IMPORTS})")

    ok = len(validator.errors) == 0
    return ok, validator.errors, validator.warnings


def structured_validate(code: str) -> Dict[str, any]:
    """
    Return a structured dict for downstream use (e.g., LLM repair loop).
    """
    ok, errors, warnings = validate_code(code)
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "mode": _SANDBOX_MODE,
        "allowed_imports": sorted(list(ALLOWED_IMPORTS)),
    }


# ---------------------------------------------------------------------------
# Stub Execution (compatibility placeholder)
# ---------------------------------------------------------------------------

def run_user_code_stub() -> dict:
    """Simple placeholder result for systems not yet executing code."""
    return {
        "table": [{"category": "A", "value": 1}, {"category": "B", "value": 2}],
        "metrics": {},
        "chartData": {
            "kind": "bar",
            "labels": ["A", "B"],
            "series": [{"label": "Value", "data": [1, 2]}],
        },
        "message": f"Sandbox validation ready (mode={_SANDBOX_MODE}). Execution not yet implemented.",
    }
