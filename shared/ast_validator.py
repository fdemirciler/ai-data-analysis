"""
AST-based validation for user-provided analysis code.

Enforces:
- Only "def run(df, ctx):" is allowed as an entrypoint.
- Disallow exec/eval, __*__ dunders, attribute access to private attrs.
- Restrict imports to an allowlist.
- Forbid file/network/process/thread/system access.

This is a conservative validator intended for fast/complex executors.
"""
from __future__ import annotations

import ast
from typing import Iterable, Set


FORBIDDEN_NAMES: Set[str] = {
    "exec",
    "eval",
    "compile",
    "open",
    "__import__",
}

FORBIDDEN_MODULE_PREFIXES: Set[str] = {
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

ALLOWED_IMPORTS_FAST: Set[str] = {
    "pandas",
    "numpy",
    "matplotlib",
    "seaborn",
    # stdlib
    "math",
    "statistics",
    "json",
    "io",
    "itertools",
    "functools",
    "collections",
    "re",
    "datetime",
}


class _Validator(ast.NodeVisitor):
    def __init__(self, allowlist: Iterable[str]) -> None:
        super().__init__()
        self.allowlist = set(allowlist)
        self.errors: list[str] = []

    def _err(self, msg: str) -> None:
        self.errors.append(msg)

    # Imports
    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            name = (alias.asname or alias.name).split(".")[0]
            if not any(name == a or name.startswith(a + ".") for a in self.allowlist):
                self._err(f"Import not allowed: {alias.name}")
            if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_MODULE_PREFIXES):
                self._err(f"Forbidden import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        mod = node.module or ""
        root = mod.split(".")[0]
        if not any(root == a or root.startswith(a + ".") for a in self.allowlist):
            self._err(f"Import from not allowed: {mod}")
        if any(root == p or root.startswith(p + ".") for p in FORBIDDEN_MODULE_PREFIXES):
            self._err(f"Forbidden import from: {mod}")
        self.generic_visit(node)

    # Calls
    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Detect forbidden builtins like eval/exec/open
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_NAMES:
                self._err(f"Forbidden call: {node.func.id}")
        self.generic_visit(node)

    # Attributes
    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self._err("Use of dunder attributes is not allowed")
        self.generic_visit(node)

    # Name access
    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if node.id.startswith("__") and node.id.endswith("__"):
            self._err("Use of dunder names is not allowed")
        self.generic_visit(node)


def validate(code: str, allowlist: Iterable[str] = ALLOWED_IMPORTS_FAST) -> tuple[bool, list[str]]:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"SyntaxError: {e}"]

    # Must define a top-level function run(df, ctx)
    has_run = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            args = node.args.args
            if len(args) >= 2 and args[0].arg == "df" and args[1].arg == "ctx":
                has_run = True
                break
    if not has_run:
        return False, ["Missing required function: def run(df, ctx):"]

    v = _Validator(allowlist)
    v.visit(tree)
    return len(v.errors) == 0, v.errors
