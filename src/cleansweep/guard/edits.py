from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from cleansweep.core.models import CleanupItem


def _delete_file(ws, item: CleanupItem) -> bool:
    src = Path(ws.path) / item.unit.path
    if not src.exists():
        return False
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    dest = Path(ws.quarantine_dir) / stamp / item.unit.path
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    src.unlink()
    item.evidence.append(f"quarantined at {dest}")
    return True


def _find_def(tree: ast.Module, qualname: str, line: int | None):
    parts = qualname.split(".")
    body = tree.body
    node = None
    for part in parts:
        matches = [
            n
            for n in body
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and n.name == part
        ]
        if not matches:
            return None
        node = matches[0]
        if line is not None and len(matches) > 1:
            node = min(matches, key=lambda n: abs(n.lineno - line))
        body = node.body
    return node


def _delete_unit(ws, item: CleanupItem) -> bool:
    path = Path(ws.path) / item.unit.path
    if not path.exists() or not item.unit.name:
        return False
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    node = _find_def(tree, item.unit.name, item.unit.start_line)
    if node is None:
        return False
    lines = text.splitlines(keepends=True)
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)]) - 1
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    new = lines[:start] + lines[node.end_lineno :]
    # a class body can't be empty
    parent_is_class = "." in item.unit.name
    if parent_is_class:
        cls = _find_def(tree, item.unit.name.rsplit(".", 1)[0], None)
        if cls is not None and len(cls.body) == 1:
            indent = " " * node.col_offset
            new = lines[:start] + [f"{indent}pass\n"] + lines[node.end_lineno :]
    path.write_text("".join(new), encoding="utf-8")
    return True


def _remove_import(ws, item: CleanupItem) -> bool:
    path = Path(ws.path) / item.unit.path
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    name = item.unit.name or ""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        if item.unit.start_line and not (node.lineno <= item.unit.start_line <= node.end_lineno):
            continue
        module = getattr(node, "module", None) or ""
        keep = [
            a
            for a in node.names
            if name not in (a.asname, a.name, f"{module}.{a.name}", a.name.split(".")[0])
        ]
        if len(keep) == len(node.names):
            continue
        lines = text.splitlines(keepends=True)
        indent = " " * node.col_offset
        if keep:
            node.names = keep
            replacement = [indent + ast.unparse(node) + "\n"]
        else:
            replacement = [f"{indent}pass\n"] if node.col_offset else []
        lines[node.lineno - 1 : node.end_lineno] = replacement
        path.write_text("".join(lines), encoding="utf-8")
        return True
    return False


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _remove_dependency(ws, item: CleanupItem) -> bool:
    path = Path(ws.path) / item.unit.path
    target = _norm(item.unit.name or "")
    if not path.exists() or not target:
        return False
    if path.name == "pyproject.toml":
        import tomlkit

        doc = tomlkit.parse(path.read_text())
        deps = doc.get("project", {}).get("dependencies")
        if deps is None:
            return False
        keep = [d for d in deps if _norm(re.split(r"[<>=!~;\[ ]", d, maxsplit=1)[0]) != target]
        if len(keep) == len(deps):
            return False
        doc["project"]["dependencies"] = keep
        path.write_text(tomlkit.dumps(doc))
        return True
    lines = path.read_text().splitlines(keepends=True)
    keep = [
        ln for ln in lines if _norm(re.split(r"[<>=!~;\[ #]", ln.strip(), maxsplit=1)[0]) != target
    ]
    if len(keep) == len(lines):
        return False
    path.write_text("".join(keep))
    return True


def _format(ws, item: CleanupItem) -> bool:
    code, _ = ws.run([sys.executable, "-m", "ruff", "format", "--isolated", item.unit.path])
    return code == 0


def apply_edit(workspace, item: CleanupItem) -> bool:
    """Apply one cleanup edit to the workspace with no checks. False if nothing was applied."""
    action = item.action
    if action == "delete_file":
        return _delete_file(workspace, item)
    if action == "delete_unit":
        return _delete_unit(workspace, item)
    if action == "remove_import":
        return _remove_import(workspace, item)
    if action == "remove_dependency":
        return _remove_dependency(workspace, item)
    if action == "format":
        return _format(workspace, item)
    if action in ("replace_with", "apply_patch"):
        return bool(item.patch) and workspace.apply_patch(item.patch)
    return False


def changed_py_files(workspace, since: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AM", since],
        cwd=workspace.path,
        capture_output=True,
        text=True,
    ).stdout
    return [p for p in out.splitlines() if p.endswith(".py")]
