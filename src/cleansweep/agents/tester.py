"""Tester: the baseline (3 runs: passing, failing and flaky tests), the tests of each work
package (related tests first when the suite is slow, then the full suite), and the final suite.

The rule: never make the project worse. A test that passed in every baseline run must still
pass; a test whose file the cleanup deleted is reported as removed, not hidden."""

from __future__ import annotations

from pathlib import Path

from cleansweep.core.io import to_dict
from cleansweep.guard.guard import static_checks

from . import environment
from .tools import related_tests

NAME = "tester"
BAD = ("failed", "error")


def _run(rt, paths: list[str] | None = None):
    timeout = int(rt.cfg.get("core", {}).get("sandbox", {}).get("test_timeout_s", 900))
    result = rt.ws.run_tests(paths, timeout=timeout)
    return result, dict(rt.ws.last_statuses)


def baseline(rt) -> None:
    """BASELINE: set up the project's environment, run the suite several times and record what
    already fails or flakes."""
    rt.environment = environment.prepare(rt)
    runs = max(1, int(rt.acfg.get("baseline_runs", 3)))
    results, statuses = [], []
    for n in range(runs):
        rt.log.emit("tool_call", agent=NAME, payload={"tool": "run_tests", "args": {"run": n + 1}})
        result, status = _run(rt)
        results.append(result)
        statuses.append(status)
        rt.log.emit(
            "tool_result", agent=NAME, payload={"tool": "run_tests", "result": to_dict(result)}
        )
    ids = set().union(*statuses) if statuses else set()
    stable = sorted(t for t in ids if all(s.get(t) == "passed" for s in statuses))
    failing = sorted(t for t in ids if all(s.get(t) in BAD for s in statuses))
    flaky = sorted(set(ids) - set(stable) - set(failing))
    crashed = all(any(f.startswith("<pytest exit") for f in r.failed_ids) for r in results)
    rt.baseline = {
        "ok": not crashed,
        "runs": runs,
        "passed": len(stable),
        "failed": len(failing),
        "errors": min(r.errors for r in results),
        "flaky": flaky,
        "failing": failing,
        "stable_pass": stable,
        "duration_s": round(sorted(r.duration_s for r in results)[len(results) // 2], 2),
        "result": results[-1],
    }
    art = rt.artifact("test_statuses", {"runs": statuses})
    log = rt.artifact("test_log", getattr(rt.ws, "last_test_output", "")[-20000:])
    body = {
        k: rt.baseline[k] for k in ("ok", "runs", "passed", "failed", "errors", "flaky", "failing")
    }
    rt.board.post("baseline", NAME, body, artifacts=[art, log])
    rt.log.v1("baseline", {"test_runs": rt.ws.test_runs})


def _module_file_exists(root: Path, test_id: str) -> bool:
    module = test_id.split("::", 1)[0]
    parts = module.split(".")
    for n in range(len(parts), 0, -1):
        if (root / Path(*parts[:n])).with_suffix(".py").exists():
            return True
    return False


def compare(rt, result, statuses: dict[str, str]) -> tuple[list[str], list[str]]:
    """(new failures, tests removed with their deleted files) against the baseline."""
    base = rt.baseline or {}
    new, removed = [], []
    if any(f.startswith("<pytest exit") for f in result.failed_ids):
        return [f"the test run crashed: {result.failed_ids[0]}"], []
    root = Path(rt.ws.path)
    for test in base.get("stable_pass", []):
        status = statuses.get(test)
        if status in BAD:
            new.append(test)
        elif status is None:
            (new if _module_file_exists(root, test) else removed).append(test)
    if result.errors > base.get("errors", 0) and not new:
        new.append(f"{result.errors - base.get('errors', 0)} new test errors")
    return new, removed


def check_package(rt, pkg) -> bool:
    """Compile and import, then the tests; post the result. False means the package failed."""
    ok, log = static_checks(rt.ws, pkg.start)
    if not ok:
        return _fail(rt, pkg, "compile", log, [])
    if rt.run_budget.out_of_tests(rt.ws.test_runs):
        return _fail(rt, pkg, "budget", "the run's test-run budget is used up", [])
    related = related_tests(rt.graph, pkg.files)
    seconds = (rt.baseline or {}).get("duration_s", 0)
    if seconds > float(rt.acfg.get("full_suite_max_s", 120)):
        # a slow suite: the related tests now, the full suite once in FINAL VERIFY (and the
        # Manager reverts packages from the last one if that is worse than the baseline)
        present = [p for p in related if (Path(rt.ws.path) / p).exists()]
        if present:
            result, statuses = _run(rt, present)
            new = [t for t in compare(rt, result, statuses)[0] if t in statuses or "crashed" in t]
            pkg.verify["_tests"] = result
            if new:
                return _fail(rt, pkg, "tests", getattr(rt.ws, "last_test_output", ""), new)
        pkg.verify["full_suite"] = f"deferred to FINAL VERIFY (the suite takes {seconds:.0f} s)"
        rt.board.post(
            "test_result",
            NAME,
            {"package": pkg.package_id, "ok": True, "new_failures": [], "stage": "related tests"},
        )
        return True
    slow = seconds > float(rt.acfg.get("related_first_s", 20))
    if related and slow:
        result, statuses = _run(rt, [p for p in related if (Path(rt.ws.path) / p).exists()])
        new = [t for t in compare(rt, result, statuses)[0] if t in statuses or "crashed" in t]
        if new:
            return _fail(rt, pkg, "tests", getattr(rt.ws, "last_test_output", ""), new)
    result, statuses = _run(rt)
    new, removed = compare(rt, result, statuses)
    pkg.verify["tests_removed"] = removed
    pkg.verify["_tests"] = result
    if new:
        return _fail(rt, pkg, "tests", getattr(rt.ws, "last_test_output", ""), new)
    rt.board.post(
        "test_result",
        NAME,
        {"package": pkg.package_id, "ok": True, "new_failures": [], "stage": "tests"},
    )
    return True


def _fail(rt, pkg, stage: str, log: str, new: list[str]) -> bool:
    art = rt.artifact("test_log", (log or "")[-20000:])
    pkg.failure = {"stage": stage, "log": (log or "")[-4000:], "new_failures": new, "log_id": art}
    rt.board.post(
        "test_result",
        NAME,
        {"package": pkg.package_id, "ok": False, "new_failures": new[:20], "stage": stage},
        artifacts=[art],
    )
    return False


def final_check(rt) -> bool:
    """FINAL VERIFY: the full suite against the baseline."""
    result, statuses = _run(rt)
    new, removed = compare(rt, result, statuses)
    passed = sum(s == "passed" for s in statuses.values())
    rt.final = {
        "ok": not new,
        "new_failures": new,
        "tests_removed": removed,
        "passed": passed,
        "baseline_passed": (rt.baseline or {}).get("passed", 0),
        "result": to_dict(result),
    }
    art = rt.artifact("test_log", getattr(rt.ws, "last_test_output", "")[-20000:])
    rt.board.post(
        "final_check",
        NAME,
        {
            "ok": not new,
            "new_failures": new[:20],
            "passed": passed,
            "baseline_passed": rt.final["baseline_passed"],
        },
        artifacts=[art],
    )
    return not new
