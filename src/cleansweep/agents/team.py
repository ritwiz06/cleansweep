"""The agent team as a LangGraph StateGraph: one node per agent, the Manager as the router."""

from __future__ import annotations

import time
import traceback
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from cleansweep.core.models import EditResult

from . import (
    auditor,
    engineer,
    explorer,
    fixer,
    investigator,
    manager,
    planner,
    reporter,
    tester,
    validator,
)

RECURSION_LIMIT = 20000


class TeamState(TypedDict, total=False):
    next: str | None
    turns: int


def _tester(rt) -> None:
    phase = rt.phases.phase
    if phase == "BASELINE":
        tester.baseline(rt)
    elif phase == "EXECUTE" and not rt.reverting:
        pkg = rt.package()
        pkg.stage = "validate" if tester.check_package(rt, pkg) else "fix"
    else:
        tester.final_check(rt)


def _validator(rt) -> None:
    pkg = rt.package()
    if validator.check_package(rt, pkg):
        pkg.status = "repaired" if pkg.turns else "kept"
        pkg.stage = "commit"
    else:
        pkg.stage = "fix"


def _engineer(rt) -> None:
    if rt.reverting:
        engineer.revert_last(rt)
        return
    pkg = rt.package()
    if pkg.stage == "apply":
        engineer.apply(rt, pkg)
    else:
        engineer.commit(rt, pkg)


AGENTS = {
    "explorer": explorer.run,
    "tester": _tester,
    "auditor": auditor.run,
    "investigator": investigator.run,
    "planner": planner.run,
    "engineer": _engineer,
    "validator": _validator,
    "fixer": lambda rt: fixer.run(rt, rt.package()),
    "reporter": lambda rt: reporter.run(rt, rt.workspace_info, rt.make_patches),
}


def _guarded(rt, role: str, fn) -> None:
    """Run an agent; an unexpected error ends the run cautiously instead of crashing it."""
    start = time.time()
    try:
        fn(rt)
    except Exception as exc:
        if role == "reporter":
            raise
        rt.log.emit(
            "log",
            agent=role,
            payload={
                "level": "ERROR",
                "message": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc()[-2000:],
            },
        )
        pkg = rt.package() if rt.phases.phase == "EXECUTE" else None
        if pkg is not None and pkg.start and pkg.stage not in ("apply", "done"):
            rt.ws.rollback(pkg.start)
            pkg.status, pkg.stage = "rolled_back", "done"
            for iid in pkg.applied:
                rt.results[iid] = EditResult(iid, "rolled_back", notes=f"{role} failed: {exc}")
        rt.stopped = rt.stopped or f"{role} failed: {type(exc).__name__}: {exc}"
        manager._stop(rt, rt.stopped)
    finally:
        stats = rt.node_stats.setdefault(role, [0, 0.0])
        stats[0] += 1
        stats[1] += time.time() - start


def build(rt):
    """The compiled graph for one run."""
    graph = StateGraph(TeamState)
    graph.add_node(
        "manager", lambda s: {"next": manager.decide(rt), "turns": s.get("turns", 0) + 1}
    )
    for role, fn in AGENTS.items():
        graph.add_node(
            role,
            lambda s, role=role, fn=fn: (_guarded(rt, role, fn), {"turns": s.get("turns", 0) + 1})[
                1
            ],
        )
        graph.add_edge(role, "manager")
    graph.add_edge(START, "manager")
    graph.add_conditional_edges(
        "manager", lambda s: s.get("next") or END, {**{r: r for r in AGENTS}, END: END}
    )
    return graph.compile()


def run_team(rt) -> None:
    """Run the team from ONBOARD to DONE."""
    rt.log.emit(
        "run_start",
        agent="manager",
        payload={
            "repo_id": rt.ws.repo_id,
            "mode": rt.mode,
            "ablation": rt.ablation,
            "dry_run": rt.dry_run,
            "model": getattr(rt.llm, "model", None),
            "budget": rt.run_budget.as_dict(),
        },
    )
    rt.log.emit(
        "phase_change",
        agent="manager",
        payload={"from": None, "to": "ONBOARD", "reason": "start", "back": False},
    )
    build(rt).invoke({"next": None, "turns": 0}, {"recursion_limit": RECURSION_LIMIT})
    rt.log.emit(
        "run_end",
        agent="manager",
        payload={"phases": rt.phases.order(), "summary": getattr(rt, "summary", {})},
    )
