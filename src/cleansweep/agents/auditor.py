"""Auditor: finds candidates with v1's detectors and policies, and gives each a prior from the
slop knowledge base. Nothing is judged here; the Investigator decides."""

from __future__ import annotations

from collections import Counter

from cleansweep.core.io import to_dict
from cleansweep.reviewer import build_plan

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
