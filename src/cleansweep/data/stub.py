"""Small fixed datasets so other areas can work before the real loaders exist."""

from __future__ import annotations

import pandas as pd

from cleansweep.core.models import FEATURE_COLUMNS, AgentPatch, CommitEvent, RepoRef, Task


def load_tasks(instance_ids: list[str] | None = None) -> list[Task]:
    tasks = [
        Task(
            "demo__demo-1",
            "demo/demo",
            "0" * 40,
            "",
            "",
            ["tests/test_a.py::test_x"],
            ["tests/test_a.py::test_y"],
            "0.1",
        )
    ]
    return [t for t in tasks if instance_ids is None or t.instance_id in instance_ids]


def load_agent_patches(agents: list[str] | None = None) -> list[AgentPatch]:
    patches = [
        AgentPatch("demo__demo-1", "agent_a", "", False),
        AgentPatch("demo__demo-1", "agent_b", "", True),
    ]
    return [p for p in patches if agents is None or p.agent in agents]


def load_repos(min_agent_prs: int = 10) -> list[RepoRef]:
    return [RepoRef("aidev:demo/demo", "https://github.com/demo/demo")]


def load_history(repo: RepoRef) -> list[CommitEvent]:
    return [
        CommitEvent("a" * 40, "2026-01-01T00:00:00Z", True, "agent_a", 1, ["app.py"]),
        CommitEvent("b" * 40, "2026-01-02T00:00:00Z", False, None, None, ["app.py"]),
    ]


def load_removal_labels() -> pd.DataFrame:
    rows = []
    for i in range(20):
        row = {
            "repo_id": f"aidev:demo/r{i % 4}",
            "pr_number": i,
            "unit_key": f"m.py::f{i}",
            "label": int(i % 5 == 0),
            "category": "dead_code",
            "agent": "agent_a",
        }
        row.update(dict.fromkeys(FEATURE_COLUMNS, -1))
        rows.append(row)
    return pd.DataFrame(rows)
