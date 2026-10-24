"""Lines-of-code per harness part.

API: logical lines (no blanks, comments or docstrings) in each API/harness/<part>.py.
SDK: lines tagged `# replaces: <part>` anywhere under SDK/.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from .config import ROOT

PARTS = ["loop", "tools", "history", "memory", "context", "compaction", "caching", "tokens"]
TAG = re.compile(r"#\s*replaces:\s*([a-z, ]+)")


def logical_lines(path: Path) -> int:
    src = path.read_text(encoding="utf-8")
    doc_lines: set[int] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                doc_lines.update(range(body[0].lineno, body[0].end_lineno + 1))
    n = 0
    for i, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if s and not s.startswith("#") and i not in doc_lines:
            n += 1
    return n


def api_loc(root: Path = ROOT) -> dict:
    return {p: logical_lines(root / "API" / "harness" / f"{p}.py") for p in PARTS}


def sdk_loc(root: Path = ROOT) -> dict:
    counts = {p: 0 for p in PARTS}
    for f in sorted((root / "SDK").glob("*.py")):
        for line in f.read_text(encoding="utf-8").splitlines():
            m = TAG.search(line)
            if m:
                for part in (x.strip() for x in m.group(1).split(",")):
                    if part in counts:
                        counts[part] += 1
    return counts
