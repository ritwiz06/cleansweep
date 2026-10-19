from __future__ import annotations

import ast
import difflib
import re
from pathlib import Path

from cleansweep.analysis.graph import module_name
from cleansweep.core.models import CodeUnit


def _unified(path: str, before: list[str], after: list[str]) -> str:
    return "".join(difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}"))


def _remove_def(lines: list[str], start: int, end: int) -> list[str]:
    """Drop lines start..end (1-based) and the blank lines just above them."""
    lo = start - 1
    while lo > 0 and not lines[lo - 1].strip():
        lo -= 1
    return lines[:lo] + lines[end:]


def _rename_refs(lines: list[str], old: str, new: str) -> list[str]:
    pattern = re.compile(rf"(?<![\w.]){re.escape(old)}\b")
    return [pattern.sub(new, ln) for ln in lines]


def _insert_import(lines: list[str], tree: ast.Module, stmt: str) -> list[str]:
    imports = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
    at = imports[-1].end_lineno if imports else 0
    return lines[:at] + [stmt + "\n"] + lines[at:]


def _read(repo_dir: str, path: str) -> tuple[str, list[str]]:
    text = (Path(repo_dir) / path).read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    return text, text.splitlines(keepends=True)


def duplicate_patch(repo_dir: str, graph, dup: CodeUnit, keep: CodeUnit, node) -> str | None:
    """Diff that deletes `dup` and points its uses in the same file at `keep`."""
    if node is None or any(graph.file_of(c) != dup.path for c in graph.callers(dup.key)):
        return None
    mod = graph.modules[dup.path]
    keep_name = keep.name.split(".")[-1]
    if "." in dup.name or "." in keep.name:
        return None  # methods need a receiver; leave them to a human
    keep_mod = module_name(keep.path)
    bound = mod.aliases.get(keep_name)
    if keep_name in mod.defs and keep.path != dup.path:
        return None
    if bound is not None and bound != ("name", keep_mod, keep_name):
        return None
    text, lines = _read(repo_dir, dup.path)
    tree = ast.parse(text)
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    after = _rename_refs(_remove_def(lines, start, node.end_lineno), dup.name, keep_name)
    if keep.path != dup.path and bound is None:
        after = _insert_import(after, tree, f"from {keep_mod} import {keep_name}")
    return _unified(dup.path, lines, after)


def wrapper_patch(repo_dir: str, graph, unit: CodeUnit, node) -> str | None:
    """Diff that inlines a one-line forwarding function at its single caller in the same file."""
    callers = [c for c in graph.callers(unit.key) if "::" in c]
    if len(callers) != 1 or graph.file_of(callers[0]) != unit.path or "." in unit.name:
        return None
    target = node.body[-1].value.func
    root = target
    while isinstance(root, ast.Attribute):
        root = root.value
    mod = graph.modules[unit.path]
    if not isinstance(root, ast.Name) or (root.id not in mod.aliases and root.id not in mod.defs):
        return None
    text, lines = _read(repo_dir, unit.path)
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    after = _remove_def(lines, start, node.end_lineno)
    pattern = re.compile(rf"(?<![\w.]){re.escape(unit.name)}\(")
    after = [pattern.sub(ast.unparse(target) + "(", ln) for ln in after]
    return _unified(unit.path, lines, after)
