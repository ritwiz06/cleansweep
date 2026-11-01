"""Auditor: finds candidates with v1's detectors and policies, and gives each a prior from the
slop knowledge base. Nothing is judged here; the Investigator decides."""

from __future__ import annotations

from collections import Counter

from cleansweep.core.io import to_dict
from cleansweep.reviewer import build_plan
from cleansweep.reviewer.detectors import _settings, excluded
from cleansweep.reviewer.lines import run_line_detectors
from cleansweep.reviewer.planner import review_scope

NAME = "auditor"


def run(rt) -> None:
    """AUDIT: detect candidates, cache them and send them to the Investigator."""
    budget = rt.budget(NAME)
    rt.log.emit(
        "tool_call", agent=NAME, payload={"tool": "run_detectors", "args": {"mode": rt.mode}}
    )
    plan = build_plan(rt.ws, rt.graph, llm=None, use_llm=False, cfg=rt.cfg)
    counts = Counter(i.category for i in plan.items)
    rt.log.emit(
        "tool_result", agent=NAME, payload={"tool": "run_detectors", "result": dict(counts)}
    )
    plan.items += line_items(rt)
    for item in plan.items:
        prior = rt.kb.prior(item.category)
        if prior:
            item.evidence.append(
                f"knowledge base: {prior:.0%} of mined maintainer removal requests are "
                f"{item.category}"
            )
        rt.items[item.item_id] = item
    art = rt.artifact("candidates", to_dict(plan.items))
    body = {
        "items": [
            {"item_id": i.item_id, "unit": i.unit.key, "category": i.category, "lane": i.lane}
            for i in plan.items
        ]
    }
    rt.board.post("candidates", NAME, body, artifacts=[art])
    rt.record_usage(NAME, budget)


def line_items(rt) -> list:
    """The line-level detectors (a second Auditor instance), in the same scope as v1's."""
    agent = f"{NAME}#lines"
    scope = review_scope(rt.ws.repo_id, rt.ws.path, rt.graph, rt.cfg)
    paths = sorted(f for f in scope.files if f.endswith(".py")) if scope is not None else None
    rt.log.emit(
        "tool_call",
        agent=agent,
        payload={
            "tool": "run_line_detectors",
            "args": {"files": len(paths) if paths is not None else "all"},
        },
    )
    items = run_line_detectors(rt.ws.path, paths)
    skip = _settings(rt.cfg)["exclude"]
    items = [
        i
        for i in items
        if not excluded(i.unit.path, skip)
        and (scope is None or scope.covers_line(i.unit.path, i.unit.start_line))
    ]
    rt.log.emit(
        "tool_result",
        agent=agent,
        payload={"tool": "run_line_detectors", "result": dict(Counter(i.category for i in items))},
    )
    return items
