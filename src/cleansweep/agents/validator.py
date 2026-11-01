"""Validator: checks a package beyond the tests: the AST for formatting-only packages, the
dependency-uninstall check, the public-API check and differential probes."""

from __future__ import annotations

from cleansweep.core.io import to_dict
from cleansweep.guard.guard import ast_unchanged, check_dependencies
from cleansweep.reviewer.detectors import has_package_metadata, is_public_api

from .coverage_probes import probe_with_coverage
from .llm import acting

NAME = "validator"
EXTRA_ROUNDS = {"thorough": 2}  # probe rounds beyond probe_rounds
REWRITES = ("replace_with", "apply_patch")  # code rewrites, not deletions


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
        if guard_cfg.get("diff_tests", True):
            settings = rt.acfg.get(NAME) or {}
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
        if (rt.brief or {}).get("ui_framework"):
            checks["ui"] = "not run: the UI snapshot check comes in a later version"
        return _pass(rt, pkg, checks)
    finally:
        rt.record_usage(NAME, budget)


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
