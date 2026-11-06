"""Validator: checks a package beyond the tests: the AST for formatting-only packages, the
dependency-uninstall check, the public-API check, differential probes and, for Textual apps,
the UI snapshot check."""

from __future__ import annotations

import re

from cleansweep.core.io import to_dict
from cleansweep.guard import ui_check
from cleansweep.guard.difftest import import_name
from cleansweep.guard.guard import ast_unchanged, check_dependencies
from cleansweep.reviewer.detectors import has_package_metadata, is_public_api

from .coverage_probes import probe_with_coverage
from .llm import acting

NAME = "validator"
EXTRA_ROUNDS = {"thorough": 2}  # probe rounds beyond probe_rounds
REWRITES = ("replace_with", "apply_patch")  # code rewrites, not deletions
# with no usable tests: removals a module check covers, and edits no probe can cover
REMOVALS = ("delete_unit", "remove_import")
UNPROBED = ("delete_file", "remove_dependency")


def check_package(rt, pkg) -> bool:
    """Run the package's checks; post the result. False means the package failed."""
    budget = rt.budget(NAME)
    items = [rt.items[i] for i in pkg.applied]
    checks: dict = {}
    try:
        if all(
            i.action == "format" or i.category in ("commented_code", "todo_note") for i in items
        ):
            same = ast_unchanged(rt.ws, pkg.start)
            checks["ast_equal"] = same
            if not same:
                return _fail(rt, pkg, "ast", "formatting changed the code structure (AST)", checks)
            return _pass(rt, pkg, checks)
        deps = [i.unit.name for i in items if i.action == "remove_dependency" and i.unit.name]
        if deps:
            info: dict = {}
            ok = check_dependencies(rt.ws, rt.baseline["result"], deps, info)
            checks["dependencies"] = info.get("dependencies", {})
            if not ok:
                return _fail(rt, pkg, "dependency", info.get("log", ""), checks)
            pins = _pins(rt, pkg, items, checks["dependencies"])
            if pins:
                return _fail(rt, pkg, "dependency", "; ".join(pins), checks)
        public = [
            i.unit.key
            for i in items
            if i.action == "delete_unit" and is_public_api(rt.ws.path, i.unit)
        ]
        checks["public_api_removed"] = public
        if public and rt.mode == "safe" and has_package_metadata(rt.ws.path):
            return _fail(
                rt,
                pkg,
                "public_api",
                f"removes public API of a published package: {public}",
                checks,
            )
        guard_cfg = rt.cfg.get("core", {}).get("guard", {})
        settings = rt.acfg.get(NAME) or {}
        outcome, info = None, {}
        if guard_cfg.get("diff_tests", True):
            with acting(NAME, budget):
                outcome, info = probe_with_coverage(
                    rt.ws,
                    pkg.start,
                    items,
                    rt.graph,
                    rt.llm,
                    guard_cfg,
                    rounds=int(settings.get("probe_rounds", 3)) + EXTRA_ROUNDS.get(rt.mode, 0),
                    target=float(settings.get("coverage_target", 0.9)),
                    guided=rt.ablation != "no_coverage",  # off: one round, as v1's Guard
                )
            checks["probes"] = to_dict(outcome) if outcome is not None else None
            checks["probe_note"] = info.get("note", "")
            checks["coverage"] = info.get("coverage")
            checks["probe_rounds"] = info.get("rounds")
            pkg.verify["_probes"] = outcome
            pkg.verify["coverage"] = info.get("coverage")
            if info.get("coverage") is not None:
                rt.log.emit(
                    "check",
                    agent=NAME,
                    payload={
                        "package": pkg.package_id,
                        "check": "probe coverage",
                        "coverage": info["coverage"],
                        "rounds": info.get("rounds"),
                    },
                )
            if outcome is not None and not outcome.same:
                log = "probes found a behavior change:\n" + "\n".join(outcome.mismatches[:20])
                return _fail(rt, pkg, "probes", log, checks)
            cases = info.get("cases_by_target", {})
            rewrites = [
                i.unit.key for i in items if i.action in REWRITES and not cases.get(i.unit.key)
            ]
            if rewrites:
                # tests rarely cover what a merged duplicate or inlined wrapper does differently
                log = f"the probes ran no cases, so these rewrites are not verified: {rewrites}"
                return _fail(rt, pkg, "unverified", log, checks)
            observed = info.get("observed_by_target", {})
            blind = [
                i.unit.key
                for i in items
                if i.action in REWRITES and not observed.get(i.unit.key, cases.get(i.unit.key))
            ]
            if blind:
                log = (
                    "every probe case on these rewrites returned None, so a changed side effect "
                    f"would not show: {blind}"
                )
                return _fail(rt, pkg, "unverified", log, checks)
        if rt.untested:
            gaps = unprobed(items, outcome, info, float(settings.get("coverage_target", 0.9)))
            if gaps:
                log = f"no usable tests, and the probes do not cover these edits: {gaps}"
                return _fail(rt, pkg, "untested", log, checks)
        checks["ui"], log = _ui(rt, pkg, items)
        if log:
            return _fail(rt, pkg, "ui", log, checks)
        return _pass(rt, pkg, checks)
    finally:
        rt.record_usage(NAME, budget)


def unprobed(items, outcome, info: dict, target: float) -> list[str]:
    """With no usable tests, the edits the probes did not cover. A removal is covered when its
    module imported before the change and the module check passed; any other edit when the
    probes ran at least `target` of the changed lines. Nothing is covered when the probes did
    not run or found a difference."""
    if outcome is None or not outcome.same:
        return [i.unit.key for i in items]
    checked = set(info.get("modules_checked", []))
    reached = info.get("coverage") or 0.0
    return [
        i.unit.key
        for i in items
        if not (import_name(i.unit.path) in checked if i.action in REMOVALS else reached >= target)
    ]


def hold_unprobed(rt) -> None:
    """With no usable tests, these stay suggestions: file and dependency removals (no probe
    covers them) and removals of public API (code outside the project may use it)."""
    for item in rt.safe_items():
        if item.action in UNPROBED:
            item.lane = "suggest"
            item.reason += " Held: no usable tests, and no probe can check this removal."
        elif item.action == "delete_unit" and is_public_api(rt.ws.path, item.unit):
            item.lane = "suggest"
            item.reason += " Held: no usable tests, and it is public API."


def pinned_spec(text: str, name: str) -> str | None:
    """The requirement declared for name in a dependency file when it has a version
    specifier (numpy==1.26.4, numpy>=1.2), else None."""
    pattern = "[-_.]".join(map(re.escape, re.split(r"[-_.]", name)))
    found = re.search(
        rf"""(?i)(?:^|[\s"',\[])({pattern}\s*(?:\[[^\]]*\])?\s*[<>=!~][^"'\n,;#]*)""", text
    )
    return found.group(1).strip() if found else None


def _pins(rt, pkg, items, states: dict) -> list[str]:
    """Removed dependencies that pin the version of a package another dependency needs: the
    tests still pass (it stays installed), but a fresh install would resolve another version."""
    out = []
    for item in items:
        state = states.get(item.unit.name or "", "")
        if item.action != "remove_dependency" or "required by" not in state:
            continue
        text = rt.ws._git("show", f"{pkg.start}:{item.unit.path}", check=False)
        spec = pinned_spec(text, item.unit.name)
        if spec:
            users = state.split("required by", 1)[1].strip(" )")
            out.append(
                f"{spec} pins the version of a package that {users} needs; removing it changes "
                "what a fresh install resolves"
            )
    return out


def ui_baseline(rt) -> None:
    """BASELINE, for a Textual app: snapshot every screen and widget twice."""
    modules = ui_check.textual_modules(rt.ws.path)
    try:
        rt.ui_base = ui_check.baseline(rt.ws, modules)
    except RuntimeError as exc:
        rt.ui_base = {"error": str(exc)}
    snap = rt.ui_base.get("snapshot") or {}
    body = {"ok": "snapshot" in rt.ui_base}
    if body["ok"]:
        body |= {
            "classes": len(snap["classes"]),
            "unstable": len(rt.ui_base["unstable"]),
            "import_errors": len(snap["import_errors"]),
        }
    else:
        body["reason"] = rt.ui_base["error"][:300]
    art = rt.artifact("ui_snapshot", rt.ui_base)
    rt.board.post("ui_baseline", NAME, body, artifacts=[art])


def _ui(rt, pkg, items) -> tuple[object, str | None]:
    """The UI check's record for a package, and the failure log when it changed the UI."""
    framework = (rt.brief or {}).get("ui_framework")
    if framework != "textual":
        why = (
            f"the project's UI uses {framework}; the snapshot check supports Textual apps"
            if framework
            else "the project has no UI framework"
        )
        return f"not applicable: {why}", None
    base = rt.ui_base or {}
    if "snapshot" not in base:
        return f"not run: {base.get('error', 'no baseline snapshot')[:300]}", None
    try:
        after = ui_check.snapshot(rt.ws, base["modules"])
    except RuntimeError as exc:
        return {
            "ok": False,
            "error": str(exc)[:300],
        }, f"the UI harness failed after the package: {exc}"
    result = ui_check.compare(base, after, ui_check.deleted_names(items))
    rt.log.emit(
        "check",
        agent=NAME,
        payload={"package": pkg.package_id, "check": "ui"}
        | {k: result[k] for k in ("ok", "classes", "changed", "lost", "removed", "broken")},
    )
    if result["ok"]:
        return result, None
    found = [f"{k}: {result[k][:5]}" for k in ("changed", "lost", "broken") if result[k]]
    return result, "the UI check found a difference: " + "; ".join(found)


def _pass(rt, pkg, checks: dict) -> bool:
    pkg.verify["checks_result"] = checks
    probes = checks.get("probes") or None
    rt.board.post(
        "validation",
        NAME,
        {
            "package": pkg.package_id,
            "ok": True,
            "probes": probes,
            "coverage": checks.get("coverage"),
            "checks": _plain(checks),
        },
    )
    return True


def _fail(rt, pkg, stage: str, log: str, checks: dict) -> bool:
    pkg.verify["checks_result"] = checks
    art = rt.artifact("check_log", log[-20000:])
    pkg.failure = {"stage": stage, "log": log[-4000:], "new_failures": [], "log_id": art}
    rt.board.post(
        "validation",
        NAME,
        {
            "package": pkg.package_id,
            "ok": False,
            "probes": checks.get("probes"),
            "coverage": checks.get("coverage"),
            "checks": _plain(checks),
        },
        artifacts=[art],
    )
    return False


def _plain(checks: dict) -> dict:
    return {k: v for k, v in checks.items() if k != "probes"}
