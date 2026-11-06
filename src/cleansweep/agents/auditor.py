"""Auditor: finds candidates with v1's detectors and policies, and gives each a prior from the
slop knowledge base. Nothing is judged here; the Investigator decides."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from cleansweep.core.io import to_dict
from cleansweep.reviewer import build_plan
from cleansweep.reviewer.detectors import _settings, excluded
from cleansweep.reviewer.lines import run_line_detectors
from cleansweep.reviewer.planner import review_scope

NAME = "auditor"
NOTEBOOK_SKIP = {".git", ".ipynb_checkpoints", ".venv", "venv", "node_modules"}


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


def line_items(rt, agent: str = f"{NAME}#lines") -> list:
    """The line-level detectors (a second Auditor instance), in the same scope as v1's."""
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


def notebook_names(root: Path) -> dict[str, str]:
    """The names used in the code cells of the project's notebooks, each with the first
    notebook that uses it."""
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*.ipynb")):
        rel = path.relative_to(root)
        if NOTEBOOK_SKIP & set(rel.parts):
            continue
        try:
            cells = json.loads(path.read_text(encoding="utf-8")).get("cells", [])
        except (OSError, ValueError, AttributeError):
            continue
        for cell in cells:
            source = cell.get("source", "") if cell.get("cell_type") == "code" else ""
            text = "".join(source) if isinstance(source, list) else str(source)
            for name in re.findall(r"[A-Za-z_]\w*", text):
                found.setdefault(name, rel.as_posix())
    return found


def hold_notebook_uses(rt) -> None:
    """Safe candidates a notebook names stay suggestions: no test runs the notebooks."""
    used = notebook_names(Path(rt.ws.path))
    for item in rt.safe_items() if used else []:
        unit = item.unit
        names = {unit.name.split(".")[-1]} if unit.name and unit.kind != "lines" else set()
        if unit.kind == "file":
            names.add(Path(unit.path).stem)
        elif unit.kind == "dependency" and unit.name:
            names.add(unit.name.lower().replace("-", "_"))
        elif unit.kind == "import":
            names = set()  # a notebook's own import of the same name is no use of this one
        hit = next((used[n] for n in sorted(names) if n in used), None)
        if hit:
            item.lane = "suggest"
            item.reason += f" Held: {hit} uses it, and no test runs the notebooks."
