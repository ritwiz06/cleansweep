"""Manager: runs the phases, assigns work, enforces the run budget and decides when the run is
done. Rule-based on purpose: every decision is logged with the rule that made it."""

from __future__ import annotations

from cleansweep.core.io import to_dict
from cleansweep.core.models import EditResult

NAME = "manager"
MAX_TURNS = 5000


def _task(rt, agent: str, goal: str, **body) -> str:
    rt.board.post("task", NAME, {"goal": goal, **body}, recipients=[agent])
    return agent


def _go(rt, phase: str, reason: str) -> None:
    rt.phases.go(phase, reason)


def _decide(rt, rule: str, text: str, **payload) -> None:
    rt.log.emit("decision", agent=NAME, payload={"rule": rule, "text": text, **payload})


def _stop(rt, why: str) -> None:
    """Out of budget: skip the packages not started and move on safely."""
    rt.stopped = why
    _decide(rt, "budget", f"stopping early: {why}")
    rt.log.emit("budget", agent=NAME, payload={"exhausted": why})
    for pkg in rt.packages[rt.current :]:
        if pkg.stage == "apply":
            pkg.status, pkg.stage = "skipped", "done"
            for iid in pkg.items:
                rt.results[iid] = EditResult(iid, "skipped", notes=f"not applied: {why}")
    if rt.phases.phase == "EXECUTE":
        pkg = rt.package()
        if pkg is None or pkg.stage == "done":
            _go(rt, "FINAL_VERIFY", why)
    elif rt.phases.phase not in ("FINAL_VERIFY", "REPORT", "DONE"):
        _go(rt, "REPORT", why)


def finish_package(rt, pkg) -> None:
    """Record the outcome of a finished package and report it to v1 readers."""
    tests = pkg.verify.get("_tests")
    probes = pkg.verify.get("_probes")
    ast_equal = (pkg.verify.get("checks_result") or {}).get("ast_equal")
    if pkg.status in ("kept", "repaired"):
        for iid in pkg.applied:
            notes = (
                "repaired after: " + pkg.failure.get("log", "")[-1500:]
                if pkg.status == "repaired"
                else ""
            )
            deps = (pkg.verify.get("checks_result") or {}).get("dependencies", {})
            if rt.items[iid].action == "remove_dependency" and rt.items[iid].unit.name in deps:
                notes = deps[rt.items[iid].unit.name]
            rt.results[iid] = EditResult(
                iid,
                pkg.status,
                tests=tests,
                ast_equal=ast_equal,
                diff_check=probes,
                diff=rt.item_diffs.get(iid, ""),
                notes=notes,
            )
    label = {
        "kept": "kept",
        "repaired": "repaired",
        "rolled_back": "rolled back",
        "split": "split in half",
        "skipped": "skipped",
    }
    rt.log.v1(
        "check",
        {
            "n": rt.checks,
            "ok": pkg.status in ("kept", "repaired", "skipped"),
            "result": label.get(pkg.status, pkg.status),
            "statuses": {
                i: (rt.results[i].status if i in rt.results else "unknown") for i in pkg.items
            },
            "tests": to_dict(tests) if tests is not None else None,
            "ast_equal": ast_equal,
            "probes": to_dict(probes) if probes is not None else None,
            "test_runs": rt.ws.test_runs,
            "lines_removed": rt.ws.diff_stats(rt.ws.base)["lines_removed"],
            "seconds": 0.0,
        },
    )
    _decide(
        rt,
        "package_done",
        f"{pkg.package_id} {label.get(pkg.status, pkg.status)}",
        package=pkg.package_id,
        status=pkg.status,
    )


def _needs_replan(rt, pkg) -> bool:
    if pkg.status != "rolled_back":
        return False
    later = rt.packages[rt.current :]
    if any(pkg.package_id in p.depends_on for p in later):
        return True
    if rt.ablation == "no_lessons":
        return False
    for p in later:
        for iid in p.items:
            item = rt.items[iid]
            framework = rt.graph.framework_callback(item.unit.key) if item.unit.name else None
            if rt.lessons.matching(item, framework):
                return True
    return False


def decide(rt) -> str | None:
    """The agent that works next, or None when the run is over."""
    while True:
        rt.turns += 1
        phase = rt.phases.phase
        if phase not in ("FINAL_VERIFY", "REPORT", "DONE") and rt.stopped is None:
            if rt.turns > MAX_TURNS:
                _stop(rt, "the Manager's turn limit")
                continue
            if rt.run_budget.out_of_time():
                _stop(rt, "the run's time budget is used up")
                continue
        if phase == "ONBOARD":
            if rt.brief is None:
                return _task(rt, "explorer", "Write the project brief")
            _go(rt, "BASELINE", "the brief is ready")
        elif phase == "BASELINE":
            if rt.baseline is None:
                runs = int(rt.acfg.get("baseline_runs", 3))
                return _task(
                    rt,
                    "tester",
                    f"Run the test suite {runs} times for the baseline",
                    kind="baseline",
                )
            if not rt.baseline["ok"]:
                rt.plan_only = True
                _decide(
                    rt,
                    "baseline_failed",
                    "the tests could not run; the plan will be delivered as suggestions only",
                )
            _go(
                rt,
                "AUDIT",
                f"baseline: {rt.baseline['passed']} passing, {rt.baseline['failed']} failing, "
                f"{len(rt.baseline['flaky'])} flaky",
            )
        elif phase == "AUDIT":
            if not rt.audited:
                rt.audited = True
                return _task(rt, "auditor", "Find cleanup candidates")
            if not rt.items:
                _go(rt, "REPORT", "no cleanup candidates found")
            else:
                _go(rt, "INVESTIGATE", f"{len(rt.items)} candidates")
        elif phase == "INVESTIGATE":
            if not rt.investigated:
                return _task(
                    rt, "investigator", "Investigate every candidate", items=sorted(rt.items)
                )
            _go(rt, "PLAN", f"{len(rt.safe_items())} items are safe to apply")
        elif phase == "PLAN":
            if not rt.planned:
                return _task(
                    rt, "planner", "Turn the safe items into work packages and write blueprint.md"
                )
            kept = any(p.status in ("kept", "repaired") for p in rt.packages)
            if rt.dry_run:
                _go(rt, "REPORT", "dry run: the plan only")
            elif rt.plan_only:
                _go(
                    rt,
                    "REPORT",
                    "the baseline tests could not run; the plan is delivered as suggestions",
                )
            elif rt.package() is None and not kept:
                _go(rt, "REPORT", "nothing is safe to apply")
            elif rt.approve is not None and rt.approved is None:
                rt.approved = bool(rt.approve(str(rt.out / "blueprint.md")))
                _decide(rt, "approval", "plan approved" if rt.approved else "plan not approved")
            elif rt.approve is not None and not rt.approved:
                _go(rt, "REPORT", "the plan was not approved")
            else:
                _go(rt, "EXECUTE", f"{len(rt.packages) - rt.current} work packages to apply")
        elif phase == "EXECUTE":
            nxt = _execute(rt)
            if nxt:
                return nxt
        elif phase == "FINAL_VERIFY":
            if rt.final is None:
                return _task(
                    rt,
                    "tester",
                    "Run the full suite and compare it with the baseline",
                    kind="final",
                )
            if rt.final["ok"]:
                _go(rt, "REPORT", "the final suite is at least as good as the baseline")
            elif rt.phases.can_go_back("EXECUTE"):
                rt.reverting = True
                _go(
                    rt,
                    "EXECUTE",
                    f"the final suite is worse than the baseline ({rt.final['new_failures'][:3]}): "
                    "undo packages from the last one",
                )
            else:
                _go(rt, "REPORT", "the final suite is still worse than the baseline")
        elif phase == "REPORT":
            if not rt.files:
                return _task(rt, "reporter", "Write the report and deliver the branch")
            _go(rt, "DONE", "report written")
        else:
            return None


def _execute(rt) -> str | None:
    if rt.reverting:
        if rt.final is None:
            return _task(rt, "tester", "Run the full suite after the revert", kind="final")
        if rt.final["ok"] or not any(p.status in ("kept", "repaired") for p in rt.packages):
            rt.reverting = False
            _go(rt, "FINAL_VERIFY", "revert done")
            return None
        rt.final = None
        return _task(rt, "engineer", "Revert the latest kept package", kind="revert")
    pkg = rt.package()
    if pkg is None:
        _go(rt, "FINAL_VERIFY", "every work package is done")
        return None
    pid = pkg.package_id
    if pkg.stage == "apply":
        return _task(
            rt, "engineer", f"Apply {pid}: {pkg.goal}", package=pid, kind="apply", items=pkg.items
        )
    if pkg.stage == "test":
        return _task(rt, "tester", f"Test {pid}", package=pid, kind="package")
    if pkg.stage == "validate":
        return _task(rt, "validator", f"Validate {pid}", package=pid)
    if pkg.stage == "fix":
        rt.board.post(
            "failure",
            NAME,
            {"package": pid, "stage": pkg.failure.get("stage", "?")},
            artifacts=[pkg.failure["log_id"]] if pkg.failure.get("log_id") else [],
        )
        return "fixer"
    if pkg.stage == "commit":
        return _task(rt, "engineer", f"Commit {pid}", package=pid, kind="commit")
    finish_package(rt, pkg)
    rt.current += 1
    if _needs_replan(rt, pkg) and rt.phases.can_go_back("PLAN"):
        rt.planned = False
        _go(
            rt,
            "PLAN",
            f"{pid} was rolled back; later packages depend on it or a new lesson fits them",
        )
    return None
