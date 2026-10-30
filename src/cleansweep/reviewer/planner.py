from __future__ import annotations

from datetime import UTC, datetime

from cleansweep.analysis import build_graph
from cleansweep.analysis.scope import agent_scope, scope_stats
from cleansweep.core.models import CATEGORIES, CleanupPlan

from .detectors import _settings, keep_framework_callbacks, keep_public_api, run_detectors
from .judge import judge_items
from .overengineering import review_overengineering, wanted


def _scope_setting(repo_id: str) -> str:
    setting = _settings().get("scope", "auto")
    if setting == "auto":
        setting = "agent" if repo_id.startswith(("swebench:", "aidev:")) else "repo"
    return setting


def review_scope(repo_id: str, repo_dir: str, graph):
    """reviewer.scope: "agent" reviews only what the agent wrote, "repo" everything; "auto"
    (default) means agent for swebench: and aidev: targets and repo for local paths."""
    return agent_scope(repo_dir, graph) if _scope_setting(repo_id) == "agent" else None


def scope_report(repo_id: str, repo_dir: str, graph) -> dict:
    """What the Reviewer looked at, for the sweep report (analysis.scope.scope_stats): a missing
    agent scope shows as kind "missing" instead of silently reviewing the whole repository."""
    wanted = _scope_setting(repo_id) == "agent"
    return scope_stats(repo_dir, review_scope(repo_id, repo_dir, graph), wanted)


def build_plan(workspace, graph=None, llm=None, use_llm: bool = True) -> CleanupPlan:
    """Detect cleanup items in a workspace (or folder) and return them as a sorted plan."""
    repo_dir = getattr(workspace, "path", workspace)
    repo_id = getattr(workspace, "repo_id", f"local:{repo_dir}")
    graph = graph or build_graph(repo_dir)
    items = run_detectors(repo_dir, graph, review_scope(repo_id, repo_dir, graph))
    if use_llm and llm is not None:
        items = judge_items(items, repo_dir, llm, graph=graph)
        if wanted():
            # one coverage run (a test run) lets the review drop tested "can't happen" claims
            coverage = workspace.coverage_json() if hasattr(workspace, "coverage_json") else None
            items += review_overengineering(items, repo_dir, graph, llm, coverage_json=coverage)
    # after the judge, which rewrites reasons, so the policies' reasons are the ones shown
    items = keep_public_api(items, repo_dir)
    items = keep_framework_callbacks(items, graph)
    items.sort(key=lambda i: (i.lane != "safe", CATEGORIES.index(i.category), i.unit.key))
    return CleanupPlan(repo_id, datetime.now(UTC).isoformat(timespec="seconds"), items)
