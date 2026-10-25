from __future__ import annotations

from datetime import UTC, datetime

from cleansweep.analysis import build_graph
from cleansweep.core.models import CATEGORIES, CleanupPlan

from .detectors import run_detectors
from .judge import judge_items


def build_plan(workspace, graph=None, llm=None, use_llm: bool = True) -> CleanupPlan:
    """Detect cleanup items in a workspace (or folder) and return them as a sorted plan."""
    repo_dir = getattr(workspace, "path", workspace)
    repo_id = getattr(workspace, "repo_id", f"local:{repo_dir}")
    graph = graph or build_graph(repo_dir)
    items = run_detectors(repo_dir, graph)
    if use_llm and llm is not None:
        items = judge_items(items, repo_dir, llm, graph=graph)
    items.sort(key=lambda i: (i.lane != "safe", CATEGORIES.index(i.category), i.unit.key))
    return CleanupPlan(repo_id, datetime.now(UTC).isoformat(timespec="seconds"), items)
