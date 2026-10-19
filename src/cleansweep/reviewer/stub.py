"""Reviewer stub: returns the planted items of the toy repo."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cleansweep.core.models import CleanupItem, CleanupPlan, CodeUnit

from .detectors import item_id

EXPECTED = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "toy_repo_expected.json"
ACTION = {
    "leftover_file": "delete_file",
    "dead_code": "delete_unit",
    "duplicate": "report_only",
    "wrapper": "report_only",
    "unused_import": "remove_import",
    "unused_dependency": "remove_dependency",
    "security": "report_only",
    "format": "format",
}


def _unit(key: str) -> CodeUnit:
    path, _, name = key.partition("::")
    if not name:
        return CodeUnit(path, "file")
    kind = "dependency" if path.endswith(".txt") else "function"
    return CodeUnit(path, kind, name)


def run_detectors(repo_dir: str, graph=None) -> list[CleanupItem]:
    rows = json.loads(EXPECTED.read_text())["items"]
    return [
        CleanupItem(
            item_id(r["key"], r["category"]),
            _unit(r["key"]),
            r["category"],
            ACTION[r["category"]],
            r["expected_lane"],
            f"planted {r['category']}",
            ["stub"],
            ["stub"],
        )
        for r in rows
    ]


def judge_items(items: list[CleanupItem], repo_dir: str, llm) -> list[CleanupItem]:
    return items


def propose_fix(item: CleanupItem, failure_log: str, repo_dir: str, llm) -> str | None:
    return None


def build_plan(workspace, graph=None, llm=None, use_llm: bool = True) -> CleanupPlan:
    repo_dir = getattr(workspace, "path", workspace)
    return CleanupPlan(
        getattr(workspace, "repo_id", "local:toy_repo"),
        datetime.now(UTC).isoformat(timespec="seconds"),
        run_detectors(repo_dir),
    )
