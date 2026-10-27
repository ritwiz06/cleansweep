from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from cleansweep.core.models import CleanupItem, CodeUnit, EditResult, RunResult

from .difftest import (
    Target,
    defs,
    get_probes,
    import_name,
    probe_change,
    probe_versions,
    run_harness,
    segment,
    select_targets,
    sys_paths,
)
from .edits import apply_edit, changed_py_files


def _top_packages(repo_dir: str) -> list[str]:
    root = Path(repo_dir)
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / "__init__.py").exists() and p.name not in ("tests", "test")
    )


def _new_failures(base: RunResult, after: RunResult) -> list[str]:
    return [t for t in after.failed_ids if t not in set(base.failed_ids)]


def _ast_dump(path: Path) -> str | None:
    try:
        return ast.dump(ast.parse(path.read_text(encoding="utf-8")))
    except (OSError, SyntaxError):
        return None


def static_checks(ws, since: str) -> tuple[bool, str]:
    """Compile the changed files and import the top-level packages."""
    files = changed_py_files(ws, since)
    if files:
        code, out = ws.run([sys.executable, "-m", "py_compile", *files])
        if code != 0:
            return False, f"compile failed:\n{out}"
    for pkg in _top_packages(ws.path):
        code, out = ws.run([sys.executable, "-c", f"import {pkg}"])
        if code != 0:
            return False, f"import {pkg} failed:\n{out}"
    return True, ""


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def touched_targets(touched: list[CodeUnit], changes: dict, known: set[str]) -> list[Target]:
    """Probe targets for touched function units, whether or not their code changed."""
    out = []
    for unit in touched:
        before = changes.get(unit.path, (None, None))[0]
        node = defs(before).get(unit.name or "")
        module = import_name(unit.path)
        if unit.kind == "function" and node is not None and module and unit.key not in known:
            out.append(Target(unit.key, module, unit.name, segment(before, node)))
    return out


def verify(before, after, touched: list[CodeUnit], llm, cfg: dict) -> tuple[bool, dict]:
    """Compare two workspaces: same test outcomes, same AST for format-only edits, and the same
    differential-probe results (cfg: diff_tests, graph, items, probe_touched, plus the
    core.guard probe keys)."""
    cfg = cfg or {}
    base = cfg.get("baseline") or before.run_tests(None)
    ok, log = static_checks(after, after.base)
    info: dict = {"static_ok": ok, "log": log, "check": "compile"}
    if not ok:
        return False, info
    result = after.run_tests(None)
    new = _new_failures(base, result)
    info.update(tests=result, new_failures=new, check="tests")
    if new or result.errors > base.errors:
        info["log"] = getattr(after, "last_test_output", "")[-4000:]
        return False, info
    if cfg.get("format_only"):
        files = {u.path for u in touched}
        same = all(
            _ast_dump(Path(before.path) / f) == _ast_dump(Path(after.path) / f) for f in files
        )
        info.update(ast_equal=same, check="ast")
        if not same:
            return False, info
        return True, info
    if cfg.get("diff_tests", True):
        paths = sorted({u.path for u in touched if u.path.endswith(".py")})
        changes = {p: (_read(Path(before.path) / p), _read(Path(after.path) / p)) for p in paths}
        graph = cfg.get("graph")
        if graph is None:
            from cleansweep.analysis import build_graph

            graph = build_graph(before.path)
        targets, checks = select_targets(
            after.path, changes, cfg.get("items", []), graph, int(cfg.get("max_targets", 10))
        )
        if cfg.get("probe_touched"):  # also probe touched functions that did not change
            targets += touched_targets(touched, changes, {t.key for t in targets})
        probes, _ = get_probes(targets, llm, cfg)
        outcome = probe_versions(
            lambda spec, files: run_harness(before, spec, files, cfg),
            lambda spec, files: run_harness(after, spec, files, cfg),
            targets,
            checks,
            probes,
            sys_paths(before.path),
            cfg,
        )
        info.update(diff_check=outcome, check="probes")
        if outcome is not None and not outcome.same:
            info["log"] = "probes found a behavior change:\n" + "\n".join(outcome.mismatches)
            return False, info
    return True, info


class Guard:
    """Applies cleanup edits and keeps only those that leave behavior unchanged."""

    def __init__(self, workspace, llm, cfg: dict, repair_fn=None, graph=None):
        self.ws = workspace
        self.llm = llm
        self.cfg = cfg or {}
        self.repair_fn = repair_fn if self.cfg.get("repair", True) else None
        self.diff_tests = bool(self.cfg.get("diff_tests", True))
        if self.diff_tests and graph is None:
            from cleansweep.analysis import build_graph

            graph = build_graph(workspace.path)
        self.graph = graph
        self.baseline = workspace.run_tests(None)
        self._results: dict[str, EditResult] = {}

    def _verify(self, start: str, items: list[CleanupItem]) -> tuple[bool, dict]:
        ok, log = static_checks(self.ws, start)
        info: dict = {"log": log, "tests": None, "ast_equal": None, "diff_check": None}
        info["check"] = "compile"
        if not ok:
            return False, info
        result = self.ws.run_tests(None)
        info.update(tests=result, check="tests")
        new = _new_failures(self.baseline, result)
        if new or result.errors > self.baseline.errors:
            info["log"] = (
                f"new failing tests: {new}\n" + getattr(self.ws, "last_test_output", "")[-4000:]
            )
            return False, info
        if all(i.action == "format" for i in items):
            same = True
            for f in changed_py_files(self.ws, start):
                old = subprocess.run(
                    ["git", "show", f"{start}:{f}"],
                    cwd=self.ws.path,
                    capture_output=True,
                    text=True,
                ).stdout
                same &= ast.dump(ast.parse(old)) == _ast_dump(Path(self.ws.path) / f)
            info.update(ast_equal=same, check="ast")
            if not same:
                info["log"] = "formatting changed the AST"
                return False, info
            return True, info  # equal ASTs prove the same behavior; no probes needed
        if self.diff_tests:
            outcome, note = probe_change(self.ws, start, items, self.graph, self.llm, self.cfg)
            info.update(diff_check=outcome, probe_note=note, check="probes")
            if outcome is not None and not outcome.same:
                info["log"] = "probes found a behavior change:\n" + "\n".join(
                    outcome.mismatches[:20]
                )
                return False, info
        return True, info

    def check_batch(self, items: list[CleanupItem]) -> bool:
        """Apply a batch, verify it, and keep it or roll it back. False means rolled back."""
        start = self.ws.checkpoint("before batch")
        diffs: dict[str, str] = {}
        applied: list[CleanupItem] = []
        prev = start
        for item in items:
            if apply_edit(self.ws, item):
                diffs[item.item_id] = self.ws.diff(prev)
                prev = self.ws.checkpoint(f"edit {item.item_id}")
                applied.append(item)
            else:
                self._results[item.item_id] = EditResult(
                    item.item_id, "skipped", notes="edit could not be applied"
                )
        if not applied:
            return True  # nothing changed, so nothing can break
        ok, info = self._verify(start, applied)
        if ok:
            self.ws.checkpoint("batch kept")
            for item in applied:
                self._record(item, "kept", info, diffs[item.item_id])
            return True

        if len(applied) == 1 and self.repair_fn is not None:
            item = applied[0]
            fix = self.repair_fn(item, info["log"], self.ws.path, self.llm)
            if fix and self.ws.apply_patch(fix):
                ok2, info2 = self._verify(start, applied)
                diff = self.ws.diff(start)
                if ok2 and not diff.strip():
                    info["log"] = "the repair undid the edit\n" + info["log"]
                elif ok2:
                    self.ws.checkpoint("batch repaired")
                    self._record(item, "repaired", info2, diff, "repaired after: " + info["log"])
                    return True
        self.ws.rollback(start)
        for item in applied:
            notes = f"{info['check']} failed: " + info["log"][-2000:]
            self._record(item, "rolled_back", info, diffs[item.item_id], notes)
        return False

    def _record(
        self, item: CleanupItem, status: str, info: dict, diff: str, notes: str = ""
    ) -> None:
        self._results[item.item_id] = EditResult(
            item.item_id,
            status,
            tests=info.get("tests"),
            ast_equal=info.get("ast_equal"),
            diff_check=info.get("diff_check"),
            diff=diff,
            notes=notes or info.get("probe_note", ""),
        )

    def results(self) -> list[EditResult]:
        """One result per item checked so far (the latest check wins)."""
        return list(self._results.values())
