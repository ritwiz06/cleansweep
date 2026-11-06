"""Manager: runs the phases, assigns work, enforces the run budget and decides when the run is
done. The rules propose every step and log it with the rule that made it. With manager: llm (the
default when an LLM is set), the Manager also asks the LLM at each phase boundary, and after a
rolled-back package, whether to go on, go back, replan or stop; the hard rules still win."""

from __future__ import annotations

import json
import time

import jsonschema

from cleansweep.core.io import to_dict
from cleansweep.core.models import EditResult

from . import auditor, checkpoint, validator
from .llm import acting
from .protocol import REASONING_OFF, load_prompt

NAME = "manager"
MAX_TURNS = 5000
LLM_STEP_BACKS = 2  # step-backs the LLM may ask for in one run
BUDGET_WARNING = 0.85  # share of a run cap that makes the Manager ask whether to stop
UNDECIDED = {"budget", "invalid", "llm_error", "error"}  # verdicts with no decision
CHOICE_SCHEMA = {
    "type": "object",
    "required": ["choice", "reason"],
    "properties": {"choice": {"type": "string"}, "reason": {"type": "string", "minLength": 1}},
}


def _task(rt, agent: str, goal: str, **body) -> str:
    rt.board.post("task", NAME, {"goal": goal, **body}, recipients=[agent])
    return agent


def _go(rt, phase: str, reason: str) -> None:
    rt.phases.go(phase, reason)


def _decide(rt, rule: str, text: str, **payload) -> None:
    rt.log.emit("decision", agent=NAME, payload={"rule": rule, "text": text, **payload})


def _stop(rt, why: str, rule: str = "budget") -> None:
    """Out of budget (or told to stop): skip the packages not started and move on safely."""
    rt.stopped = why
    _decide(rt, rule, f"stopping early: {why}")
    if rule == "budget":
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


def _undecided(rt) -> list[str]:
    return sorted(i for i, v in rt.verdicts.items() if v.get("stop") in UNDECIDED)


def _choices(rt, proposed: str) -> dict[str, str]:
    """The options at this point: the rules' step first, then what the hard rules allow."""
    here = rt.phases.phase
    out = {"continue": proposed}
    backs_left = rt.llm_back_steps < LLM_STEP_BACKS
    undecided = _undecided(rt)
    if backs_left and undecided and here in ("INVESTIGATE", "PLAN"):
        if here == "INVESTIGATE" or rt.phases.can_go_back("INVESTIGATE"):
            out["go_back:INVESTIGATE"] = (
                f"investigate again the {len(undecided)} candidates the Investigator could not "
                "decide, with twice the steps"
            )
    if backs_left and here == "EXECUTE" and rt.phases.can_go_back("PLAN"):
        out["replan"] = "go back to PLAN: re-plan the packages not started, with the lessons so far"
    if here == "FINAL_VERIFY":
        # the suite is worse than the baseline: both options undo packages; neither may stop
        out["revert_all"] = "undo every kept package and deliver nothing"
    elif here not in ("REPORT", "DONE"):
        out["stop"] = "stop now: skip the work not started, verify what was applied, and report"
    return out


def _status(rt, proposed: str, why: str, options: dict[str, str]) -> str:
    decisions: dict[str, int] = {}
    for v in rt.verdicts.values():
        decisions[v["decision"]] = decisions.get(v["decision"], 0) + 1
    packages: dict[str, int] = {}
    for pkg in rt.packages:
        packages[pkg.status] = packages.get(pkg.status, 0) + 1
    finished = sum(packages.get(s, 0) for s in ("kept", "repaired", "rolled_back", "reverted"))
    left = sum(p.stage == "apply" for p in rt.packages[rt.current :])
    runs_left = rt.run_budget.test_runs - rt.ws.test_runs
    tests_left = (
        f"{runs_left} test runs left: enough for {max(0, min(left, runs_left - 1))} of the "
        f"{left} packages left (at least one run each) plus FINAL VERIFY (one run)"
        if rt.run_budget.test_runs
        else "no test-run cap"
    )
    base = rt.baseline or {}
    lines = [
        f"Phase: {rt.phases.phase}. The rules propose: {proposed} ({why}).",
        f"Mode: {rt.mode}. Candidates: {len(rt.items)}; verdicts {json.dumps(decisions)}; "
        f"undecided: {len(_undecided(rt))}.",
        f"Packages: {json.dumps(packages)}; rolled back {packages.get('rolled_back', 0)} of "
        f"{finished} finished; lessons: {len(rt.lessons.lessons)}.",
        f"Baseline: {base.get('passed', '?')} passing, {base.get('failed', '?')} failing, "
        f"{len(base.get('flaky', []))} flaky.",
        f"Run budget: LLM {rt.run_budget.used_llm}/{rt.run_budget.llm_calls or 'no cap'}, "
        f"minutes {(time.time() - rt.run_budget.started) / 60:.1f}/"
        f"{rt.run_budget.minutes or 'no cap'}, "
        f"test runs {rt.ws.test_runs}/{rt.run_budget.test_runs or 'no cap'}. "
        f"Packages left: {left}; {tests_left}. "
        f"Step-backs left: {LLM_STEP_BACKS - rt.llm_back_steps}.",
        "Options:",
        *(f"- {k}: {v}" for k, v in options.items()),
        'Reply with JSON only: {"choice": "<one option>", "reason": "<one sentence>"}',
    ]
    return "\n".join(lines)


def _consult(rt, proposed: str, why: str) -> str:
    """The LLM's pick at a decision point, checked against the options; "continue" (the
    rules' step) whenever the Manager is rule-based or the reply is unusable."""
    llm = rt.manager_llm or rt.llm
    if rt.manager_mode != "llm" or llm is None or rt.stopped is not None:
        return "continue"
    options = _choices(rt, proposed)
    if len(options) == 1:
        return "continue"
    options["continue"] = f"go on as the rules propose: {proposed}"
    messages = [
        {"role": "system", "content": load_prompt(NAME)},
        {"role": "user", "content": _status(rt, proposed, why, options)},
    ]
    try:
        with acting(NAME, rt.manager_budget):
            reply = llm.chat_json(messages, temperature=0.0, extra_body=REASONING_OFF)
        jsonschema.validate(reply, CHOICE_SCHEMA)
        choice, reason = reply["choice"], reply["reason"]
    except Exception as exc:  # out of budget, LLM error or a malformed reply: the rules decide
        choice, reason = "continue", f"no usable reply ({type(exc).__name__}): the rules decide"
    if choice == proposed and choice not in options:
        choice = "continue"  # the rules' step, named the way the status names it
    if choice not in options:
        choice, reason = "continue", f"{choice!r} is not an option: the rules decide"
    _decide(rt, "llm_manager", reason, choice=choice, proposed=proposed, options=sorted(options))
    return choice


def _reinvestigate(rt) -> None:
    """Undo the verdicts that never decided, so the Investigator looks again with more steps."""
    for iid in _undecided(rt):
        item = rt.items[iid]
        lane, action, reason, evidence, sources = rt.before_verdict[iid]
        item.lane, item.action, item.reason = lane, action, reason
        item.evidence, item.sources = list(evidence), list(sources)
        del rt.verdicts[iid]
        rt.retry.add(iid)
    rt.investigated = False


def _advance(rt, proposed: str, why: str) -> None:
    """Take the rules' step, unless the LLM-guided Manager picks another allowed option."""
    choice = _consult(rt, proposed, why)
    if choice == "stop":
        _stop(rt, "the Manager chose to stop", rule="llm_manager")
    elif choice == "go_back:INVESTIGATE":
        rt.llm_back_steps += 1
        _reinvestigate(rt)
        if rt.phases.phase != "INVESTIGATE":
            rt.planned = False
            _go(rt, "INVESTIGATE", "the Manager sends the undecided candidates back")
    elif choice == "replan":
        rt.llm_back_steps += 1
        rt.planned = False
        _go(rt, "PLAN", "the Manager re-plans the packages not started")
    else:
        _go(rt, proposed, why)


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
        if rt.resumable:
            checkpoint.save(rt)
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
            _advance(rt, "BASELINE", "the brief is ready")
        elif phase == "BASELINE":
            if rt.baseline is None:
                runs = int(rt.acfg.get("baseline_runs", 3))
                return _task(
                    rt,
                    "tester",
                    f"Run the test suite {runs} times for the baseline",
                    kind="baseline",
                )
            if (
                rt.ui_base is None
                and rt.baseline["ok"]
                and not rt.dry_run
                and (rt.brief or {}).get("ui_framework") == "textual"
            ):
                return _task(
                    rt,
                    "validator",
                    "Snapshot every screen and widget for the UI check",
                    kind="ui_baseline",
                )
            if not rt.baseline["ok"] and rt.acfg.get("no_tests", "plan") == "probes":
                rt.untested = True
                _decide(
                    rt,
                    "baseline_failed",
                    f"no usable tests ({rt.baseline.get('reason')}); only edits the probes cover "
                    "will be applied, not verified by tests",
                )
            elif not rt.baseline["ok"]:
                rt.plan_only = True
                _decide(
                    rt,
                    "baseline_failed",
                    "the tests could not run; the plan will be delivered as suggestions only",
                )
            _advance(
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
                _advance(rt, "INVESTIGATE", f"{len(rt.items)} candidates")
        elif phase == "INVESTIGATE":
            if not rt.investigated:
                return _task(
                    rt, "investigator", "Investigate every candidate", items=sorted(rt.items)
                )
            _advance(rt, "PLAN", f"{len(rt.safe_items())} items are safe to apply")
        elif phase == "PLAN":
            if not rt.planned:
                if rt.acfg.get("notebooks") == "hold":
                    auditor.hold_notebook_uses(rt)
                if rt.untested:
                    validator.hold_unprobed(rt)
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
                _advance(rt, "EXECUTE", f"{len(rt.packages) - rt.current} work packages to apply")
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
                why = (
                    f"the final suite is worse than the baseline ({rt.final['new_failures'][:3]}): "
                    "undo packages from the last one"
                )
                rt.reverting = True
                rt.revert_all = _consult(rt, "go_back:EXECUTE", why) == "revert_all"
                _go(rt, "EXECUTE", "undo every kept package" if rt.revert_all else why)
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
        kept = any(p.status in ("kept", "repaired") for p in rt.packages)
        if (rt.final["ok"] and not rt.revert_all) or not kept:
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
    elif rt.package() is not None:
        share, cap = rt.run_budget.used(rt.ws.test_runs)
        why = None
        if pkg.status == "rolled_back":
            why = f"{pid} was rolled back; go on with the next package"
        elif share >= BUDGET_WARNING and not rt.budget_warned:
            rt.budget_warned = True
            why = f"{share:.0%} of the run's {cap} budget is used; go on with the next package"
        choice = _consult(rt, "EXECUTE", why) if why else "continue"
        if choice == "stop":
            _stop(rt, "the Manager chose to stop", rule="llm_manager")
        elif choice == "replan":
            rt.llm_back_steps += 1
            rt.planned = False
            _go(rt, "PLAN", "the Manager re-plans the packages not started")
    return None
