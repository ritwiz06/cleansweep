from __future__ import annotations

from datetime import UTC, datetime

from cleansweep.analysis import build_graph
from cleansweep.analysis.scope import agent_scope, scope_stats
from cleansweep.core.models import CATEGORIES, CleanupPlan

from .detectors import (
    _settings,
    excluded,
    keep_framework_callbacks,
    keep_public_api,
    run_detectors,
)
from .judge import judge_items
from .overengineering import review_overengineering, wanted


def _scope_setting(repo_id: str, cfg: dict | None = None) -> str:
    setting = _settings(cfg).get("scope", "auto")
    if setting == "auto":
        setting = "agent" if repo_id.startswith(("swebench:", "aidev:")) else "repo"
    return setting


def review_scope(repo_id: str, repo_dir: str, graph, cfg: dict | None = None):
    """reviewer.scope: "agent" reviews only what the agent wrote, "repo" everything; "auto"
    (default) means agent for swebench: and aidev: targets and repo for local paths."""
    return agent_scope(repo_dir, graph) if _scope_setting(repo_id, cfg) == "agent" else None


def scope_report(repo_id: str, repo_dir: str, graph, cfg: dict | None = None) -> dict:
    """What the Reviewer looked at, for the sweep report (analysis.scope.scope_stats): a missing
    agent scope shows as kind "missing" instead of silently reviewing the whole repository."""
    wanted = _scope_setting(repo_id, cfg) == "agent"
    return scope_stats(repo_dir, review_scope(repo_id, repo_dir, graph, cfg), wanted)


def build_plan(
    workspace, graph=None, llm=None, use_llm: bool = True, cfg: dict | None = None
) -> CleanupPlan:
    """Detect cleanup items in a workspace (or folder) and return them as a sorted plan.

    cfg is a run's config: its reviewer section replaces configs/reviewer.yaml (the environment
    switches still override it). Without one, the config files are read."""
    repo_dir = getattr(workspace, "path", workspace)
    repo_id = getattr(workspace, "repo_id", f"local:{repo_dir}")
    graph = graph or build_graph(repo_dir)
    settings = _settings(cfg)
    items = run_detectors(repo_dir, graph, review_scope(repo_id, repo_dir, graph, cfg), cfg)
    items = [i for i in items if not excluded(i.unit.path, settings["exclude"])]
    if use_llm and llm is not None:
        items = judge_items(items, repo_dir, llm, graph=graph, cfg=cfg)
        if wanted(cfg):
            # one coverage run (a test run) lets the review drop tested "can't happen" claims
            coverage = workspace.coverage_json() if hasattr(workspace, "coverage_json") else None
            found = review_overengineering(
                items, repo_dir, graph, llm, coverage_json=coverage, cfg=cfg
            )
            items += [i for i in found if not excluded(i.unit.path, settings["exclude"])]
    # after the judge, which rewrites reasons, so the policies' reasons are the ones shown
    items = keep_public_api(items, repo_dir, settings["keep_public_api"])
    items = keep_framework_callbacks(items, graph, settings["framework_callbacks"])
    items.sort(key=lambda i: (i.lane != "safe", CATEGORIES.index(i.category), i.unit.key))
    return CleanupPlan(repo_id, datetime.now(UTC).isoformat(timespec="seconds"), items)
