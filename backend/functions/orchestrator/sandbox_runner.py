"""
Sandbox runner scaffolding for executing LLM-generated analysis code.

Milestone 1 status: this module provides interfaces and validation but does not
execute arbitrary code yet. Future milestones will add a dedicated subprocess
runner with a 60s hard timeout and a soft-timeout warning (log-only).

Constraints:
- Allowlist imports: pandas, numpy, math, json
- No filesystem, network, process or thread access
- Required entrypoint signature: def run(df, ctx): -> dict
- Expected RESULT shape: { "table": list[dict], "metrics": dict, "chartData": dict, "message": str? }
"""
from __future__ import annotations

import ast
from typing import Iterable, Tuple

ALLOWED_IMPORTS = {"pandas", "numpy", "math", "json"}
FORBIDDEN_NAMES = {"exec", "eval", "compile", "open", "__import__"}
FORBIDDEN_PREFIXES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "asyncio",
    "multiprocessing",
    "threading",
    "ctypes",
    "pathlib",
    "importlib",
    "pdb",
    "pickle",
    "dill",
    "requests",
    "urllib",
}


class _Validator(ast.NodeVisitor):
    def __init__(self, allowlist: Iterable[str]):
        super().__init__()
        self.allowlist = set(allowlist)
        self.errors: list[str] = []

    def _err(self, msg: str) -> None:
        self.errors.append(msg)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            name = (alias.asname or alias.name).split(".")[0]
            if name not in self.allowlist:
                self._err(f"Import not allowed: {alias.name}")
            if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
                self._err(f"Forbidden import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        mod = node.module or ""
        root = mod.split(".")[0]
        if root not in self.allowlist:
            self._err(f"Import from not allowed: {mod}")
        if any(root == p or root.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
            self._err(f"Forbidden import from: {mod}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_NAMES:
            self._err(f"Forbidden call: {node.func.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self._err("Use of dunder attributes is not allowed")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if node.id.startswith("__") and node.id.endswith("__"):
            self._err("Use of dunder names is not allowed")
        self.generic_visit(node)


def validate_code(code: str) -> Tuple[bool, list[str]]:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:  # pragma: no cover - surfaced to caller
        return False, [f"SyntaxError: {e}"]

    # Must define def run(df, ctx):
    has_run = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            args = node.args.args
            if len(args) >= 2 and args[0].arg == "df" and args[1].arg == "ctx":
                has_run = True
                break
    if not has_run:
        return False, ["Missing required function: def run(df, ctx):"]

    v = _Validator(ALLOWED_IMPORTS)
    v.visit(tree)
    return len(v.errors) == 0, v.errors


def run_user_code_stub() -> dict:
    """Milestone 1 stub: placeholder RESULT until sandbox execution is implemented."""
    return {
        "table": [{"category": "A", "value": 1}, {"category": "B", "value": 2}],
        "metrics": {},
        "chartData": {
            "kind": "bar",
            "labels": ["A", "B"],
            "series": [{"label": "Value", "data": [1, 2]}],
        },
        "message": "Sandbox execution not yet implemented",
    }
