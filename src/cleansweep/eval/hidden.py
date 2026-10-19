from __future__ import annotations

import shutil
from pathlib import Path

from cleansweep.analysis.graph import is_test_file, iter_py_files
from cleansweep.sandbox import open_workspace

HIDDEN_DIR = "_hidden_checks"


def _hidden_source(target: str, cfg: dict) -> Path | None:
    explicit = cfg.get("exp", {}).get("hidden_tests") or cfg.get("hidden_tests")
    if explicit:
        return Path(explicit)
    sibling = Path(target.rstrip("/") + "_hidden")
    return sibling if sibling.is_dir() else None


def _loc(repo_dir: str) -> int:
    return sum(
        len((Path(repo_dir) / p).read_text(errors="replace").splitlines())
        for p in iter_py_files(repo_dir)
        if not is_test_file(p) and not p.startswith(HIDDEN_DIR)
    )


def _outcomes(result) -> dict:
    return {
        "passed": result.passed,
        "failed": result.failed,
        "errors": result.errors,
        "failed_ids": sorted(result.failed_ids),
    }


def run_hidden_checks(target: str, final_diff: str, cfg: dict) -> dict:
    """Run checks the Guard never saw, before and after the cleanup diff, and compare."""
    src = _hidden_source(target, cfg)
    if src is None:
        return {"available": False}
    ws = open_workspace(target, cfg.get("core", {}).get("sandbox"))
    try:
        shutil.copytree(src, Path(ws.path) / HIDDEN_DIR)
        loc_before = _loc(ws.path)
        hidden_before = ws.run_tests([HIDDEN_DIR])
        visible_before = ws.run_tests(None)
        applied = ws.apply_patch(final_diff) if final_diff.strip() else True
        if not applied:
            return {"available": True, "applied": False, "behavior_changed": None}
        hidden_after = ws.run_tests([HIDDEN_DIR])
        visible_after = ws.run_tests(None)
        changed = (
            sorted(hidden_before.failed_ids) != sorted(hidden_after.failed_ids)
            or hidden_before.errors != hidden_after.errors
        )
        return {
            "available": True,
            "applied": True,
            "behavior_changed": changed,
            "hidden_before": _outcomes(hidden_before),
            "hidden_after": _outcomes(hidden_after),
            "visible_new_failures": sorted(
                set(visible_after.failed_ids) - set(visible_before.failed_ids)
            ),
            "loc_before": loc_before,
            "loc_after": _loc(ws.path),
        }
    finally:
        ws.close()
