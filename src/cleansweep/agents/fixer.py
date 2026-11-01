"""Fixer: after a failed check, splits a multi-item package, repairs a single edit in at most
2 turns, or rolls it back. Every rollback writes a lesson."""

from __future__ import annotations

from cleansweep.core.models import EditResult
from cleansweep.reviewer import propose_fix

from .lessons import pattern_for
from .llm import acting
from .protocol import load_prompt
from .runtime import Package

NAME = "fixer"
REPAIRABLE = ("compile", "tests", "probes")


class WithSystem:
    """An LLM whose requests start with the Fixer's own system prompt."""

    def __init__(self, llm, system: str):
        self.llm, self.system = llm, system

    def chat(self, messages, temperature=0.0, seed=None, extra_body=None):
        return self.llm.chat(
            [{"role": "system", "content": self.system}, *messages], temperature, seed, extra_body
        )


def run(rt, pkg: Package) -> str:
    """Handle the current package's failure: "split", "retry" or "rolled_back"."""
    budget = rt.budget(NAME)
    try:
        failure = pkg.failure
        if len(pkg.applied) > 1:
            return _split(rt, pkg)
        item = rt.items[pkg.applied[0]]
        turns = int((rt.acfg.get(NAME) or {}).get("turns", 2))
        if rt.llm is not None and pkg.turns < turns and failure.get("stage") in REPAIRABLE:
            with acting(NAME, budget):
                try:
                    fix = propose_fix(
                        item,
                        failure.get("log", ""),
                        rt.ws.path,
                        WithSystem(rt.llm, load_prompt(NAME)),
                    )
                except Exception:  # budget or LLM failure: no fix
                    fix = None
            if fix and rt.ws.apply_patch(fix):
                pkg.turns += 1
                pkg.stage = "test"
                rt.board.post(
                    "repair",
                    NAME,
                    {"package": pkg.package_id, "outcome": "retry", "turns": pkg.turns},
                )
                return "retry"
        return rollback(rt, pkg)
    finally:
        rt.record_usage(NAME, budget)


def _split(rt, pkg: Package) -> str:
    rt.ws.rollback(pkg.start)
    half = len(pkg.applied) // 2
    parts = [pkg.applied[:half], pkg.applied[half:]]
    new = []
    for suffix, part in zip("ab", parts, strict=True):
        new.append(
            Package(
                package_id=f"{pkg.package_id}{suffix}",
                goal=pkg.goal + f" (part {suffix})",
                items=part,
                files=sorted({rt.items[i].unit.path for i in part}),
                risk=pkg.risk,
                depends_on=list(pkg.depends_on),
                verify={
                    k: v
                    for k, v in pkg.verify.items()
                    if k in ("related_tests", "checks", "probe_targets")
                },
                rollback=pkg.rollback,
            )
        )
    pkg.status, pkg.stage = "split", "done"
    rt.packages[rt.current + 1 : rt.current + 1] = new
    rt.board.post(
        "repair", NAME, {"package": pkg.package_id, "outcome": "split", "turns": pkg.turns}
    )
    return "split"


def rollback(rt, pkg: Package) -> str:
    """Undo the package, record why, and write a lesson."""
    rt.ws.rollback(pkg.start)
    failure = pkg.failure
    pkg.status, pkg.stage = "rolled_back", "done"
    for iid in pkg.applied:
        rt.results[iid] = EditResult(
            iid,
            "rolled_back",
            diff=rt.item_diffs.get(iid, ""),
            notes=f"{failure.get('stage')} failed: " + failure.get("log", "")[-2000:],
        )
    if rt.ablation != "no_lessons" and len(pkg.applied) == 1:
        item = rt.items[pkg.applied[0]]
        framework = rt.graph.framework_callback(item.unit.key) if item.unit.name else None
        first = next((ln.strip() for ln in failure.get("log", "").splitlines() if ln.strip()), "")
        reason = f"{failure.get('stage')} failed after {item.action} of {item.unit.key}: {first}"[
            :300
        ]
        lesson = rt.lessons.add(
            pattern_for(item, framework),
            rt.redact(reason),
            {"package": pkg.package_id, "item": item.item_id, "check": failure.get("stage")},
        )
        rt.log.emit("lesson", agent=NAME, payload=lesson)
        rt.board.post(
            "lesson",
            NAME,
            {
                "lesson_id": lesson["lesson_id"],
                "pattern": lesson["pattern"],
                "reason": lesson["reason"],
            },
        )
    rt.board.post(
        "repair", NAME, {"package": pkg.package_id, "outcome": "rolled_back", "turns": pkg.turns}
    )
    return "rolled_back"
