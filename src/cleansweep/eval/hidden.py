from __future__ import annotations

import shutil
from pathlib import Path

from cleansweep.analysis.graph import is_test_file, iter_py_files
from cleansweep.sandbox import open_workspace

HIDDEN_DIR = "_hidden_checks"
START, END = ">>>>> Start Test Output", ">>>>> End Test Output"


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


def _status(ws, test_paths: list[str] | None) -> dict[str, str]:
    """Test name -> status for one run, read with the instance's swebench log parser."""
    ws.run_tests(test_paths)
    out = getattr(ws, "last_test_output", "")
    section = out.split(START, 1)[-1].split(END, 1)[0]
    return ws.parser(section, ws.spec) or ws.parser(out, ws.spec)


def _hidden_status(ws, files: list[str]) -> dict[str, str]:
    """Run the hidden test files together; if that gives no results (one file can stop
    collection for all), run them one at a time."""
    if not files:
        return {}
    status = _status(ws, files)
    if status:
        return status
    merged: dict[str, str] = {}
    for f in files:
        merged.update(_status(ws, [f]))
    return merged


def run_swebench_hidden(target: str, final_diff: str, cfg: dict) -> dict:
    """Hidden checks for "swebench:<instance>:<agent>": the instance's FAIL_TO_PASS and
    PASS_TO_PASS tests plus PatchDiff's generated tests for this patch, in a fresh container,
    before and after the cleanup diff. The sweep's workspace never contains the PatchDiff tests.
    """
    from cleansweep.data import load_agent_patches
    from cleansweep.data.swebench import data_path

    _, instance_id, agent = target.split(":", 2)
    found = [p for p in load_agent_patches([agent]) if p.instance_id == instance_id]
    hidden = found[0].hidden_tests if found else []
    sandbox = {**cfg.get("core", {}).get("sandbox", {}), "flaky_runs": 0}
    ws = open_workspace(target, sandbox)
    try:
        folder = Path(ws.test_files[0]).parent if ws.test_files else Path(".")
        files = []
        for k, rel in enumerate(hidden):
            dest = folder / f"test_cs_hidden_{k}.py"
            (Path(ws.path) / dest).write_text(data_path(rel).read_text(encoding="utf-8"))
            files.append(dest.as_posix())
        named = set(ws.row["FAIL_TO_PASS"]) | set(ws.row["PASS_TO_PASS"])
        loc_before = _loc(ws.path)
        visible_before = _status(ws, None)
        # a PatchDiff test counts only if it gives the same result on every run before the diff
        runs = max(2, int(cfg.get("exp", {}).get("hidden_stability_runs", 3)))
        first, *others = [_hidden_status(ws, files) for _ in range(runs)]
        stable = {t: v for t, v in first.items() if all(o.get(t) == v for o in others)}
        if final_diff.strip() and not ws.apply_patch(final_diff):
            return {"available": True, "applied": False, "behavior_changed": None}
        visible_after = _status(ws, None)
        hidden_after = _hidden_status(ws, files)
        named_changed = sorted(t for t in named if visible_before.get(t) != visible_after.get(t))
        hidden_changed = sorted(t for t, v in stable.items() if hidden_after.get(t) != v)
        failing = ("FAILED", "ERROR")
        return {
            "available": True,
            "applied": True,
            "behavior_changed": bool(named_changed or hidden_changed),
            "f2p_p2p_changed": named_changed,
            "patchdiff_changed": hidden_changed,
            "patchdiff_files": len(files),
            "patchdiff_tests": len(stable),
            "patchdiff_unstable": len(first) - len(stable),
            "hidden_before": {"failed_ids": sorted(t for t, v in stable.items() if v in failing)},
            "hidden_after": {
                "failed_ids": sorted(t for t in stable if hidden_after.get(t) in failing)
            },
            "visible_new_failures": sorted(
                t
                for t, v in visible_after.items()
                if v in failing and visible_before.get(t) not in failing
            ),
            "loc_before": loc_before,
            "loc_after": _loc(ws.path),
        }
    finally:
        ws.close()


def run_hidden_checks(target: str, final_diff: str, cfg: dict) -> dict:
    """Run checks the Guard never saw, before and after the cleanup diff, and compare."""
    if target.startswith("swebench:"):
        return run_swebench_hidden(target, final_diff, cfg)
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
