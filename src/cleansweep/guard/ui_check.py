"""UI snapshot check for Textual apps: what every screen and widget shows, before and after a
work package.

ui_harness.py runs in the project's environment (its container for AIDev targets): it mounts
each Textual screen and widget class of the project headless with App.run_test and records the
widget tree and the visible text. The baseline is taken twice; a class whose snapshot differs
between those two runs of the same code is unstable and left out. After a package, any stable
class that shows something else, disappears without the package deleting it, or a module that
stops importing fails the check.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

from cleansweep.analysis.graph import import_name

from .difftest import PROBE_DIR

HARNESS = Path(__file__).parent / "ui_harness.py"
MARK = "CS_UI_JSON "
TEXTUAL = re.compile(r"^\s*(?:from|import)\s+textual\b", re.M)
SKIP_DIRS = {"tests", "test", "docs", "examples", PROBE_DIR, "node_modules", "build", "dist"}


def textual_modules(repo_dir: str) -> list[str]:
    """Dotted names of the project's modules that import textual (tests left out)."""
    root = Path(repo_dir)
    out = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        parts = rel.split("/")
        if any(p in SKIP_DIRS or p.startswith(".") for p in parts[:-1]):
            continue
        if parts[-1].startswith("test_") or parts[-1] == "conftest.py":
            continue
        if TEXTUAL.search(path.read_text(encoding="utf-8", errors="ignore")):
            out.append(import_name(rel))
    return out


def _untracked(ws) -> set[str]:
    out = ws._git("status", "--porcelain", "--untracked-files=all", check=False)
    return {line[3:] for line in out.splitlines() if line.startswith("?? ")}


def snapshot(ws, modules: list[str], timeout: int = 900) -> dict:
    """Run the harness in the workspace: {"import_errors": {...}, "classes": {...}}. Files the
    app writes into the project while it is mounted are removed."""
    run_dir = Path(PROBE_DIR) / f"ui_{uuid.uuid4().hex[:12]}"
    folder = Path(ws.path) / run_dir
    folder.mkdir(parents=True)
    before = _untracked(ws)
    try:
        shutil.copy(HARNESS, folder / "ui_harness.py")
        if hasattr(ws, "sync"):
            ws.sync()
        cmd = [ws.python, (run_dir / "ui_harness.py").as_posix(), json.dumps(modules)]
        code, out = ws.run(cmd, timeout=timeout)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        for rel in _untracked(ws) - before:
            (Path(ws.path) / rel).unlink(missing_ok=True)
    line = next((x for x in reversed(out.splitlines()) if x.startswith(MARK)), None)
    if line is None:
        raise RuntimeError(f"the UI harness did not finish (exit {code}): {out[-300:]}")
    return json.loads(line[len(MARK) :])


def baseline(ws, modules: list[str]) -> dict:
    """Two snapshots of the unchanged project; classes that differ between them are unstable."""
    first, second = snapshot(ws, modules), snapshot(ws, modules)
    unstable = sorted(n for n, s in first["classes"].items() if second["classes"].get(n) != s)
    return {"modules": modules, "snapshot": first, "unstable": unstable}


def deleted_names(items) -> set[str]:
    """Dotted names of the classes and modules a package's items delete."""
    out = set()
    for item in items:
        unit = item.unit
        if not unit.path.endswith(".py"):
            continue
        if item.action == "delete_file":
            out.add(import_name(unit.path))
        elif item.action == "delete_unit" and unit.name:
            out.add(f"{import_name(unit.path)}.{unit.name}")
    return out


def compare(base: dict, after: dict, deleted: set[str]) -> dict:
    """What a package changed: stable classes whose snapshot differs ("changed"), classes gone
    that the package did not delete ("lost"), those it did ("removed"), and modules that stopped
    importing ("broken")."""
    before = base["snapshot"]
    stable = [n for n in before["classes"] if n not in set(base["unstable"])]
    changed = [
        n for n in stable if n in after["classes"] and after["classes"][n] != before["classes"][n]
    ]
    gone = [n for n in stable if n not in after["classes"]]
    removed = [n for n in gone if n in deleted or n.rsplit(".", 1)[0] in deleted]
    lost = [n for n in gone if n not in removed]
    new_errors = set(after["import_errors"]) - set(before["import_errors"])
    broken = sorted(m for m in new_errors if m not in deleted)
    return {
        "ok": not (changed or lost or broken),
        "classes": len(stable),
        "unstable": len(base["unstable"]),
        "changed": changed,
        "lost": lost,
        "removed": removed,
        "broken": broken,
    }
