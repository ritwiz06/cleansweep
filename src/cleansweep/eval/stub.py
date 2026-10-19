from __future__ import annotations

from pathlib import Path

from cleansweep.core.io import load_json
from cleansweep.core.models import SweepReport

SAMPLE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sample_report.json"


def _sample(target: str, method: str) -> SweepReport:
    report = load_json(SweepReport, SAMPLE)
    report.repo_id, report.method = f"local:{Path(target).name}", method
    return report


def tools_only(target: str, cfg: dict) -> SweepReport:
    return _sample(target, "tools_only")


def one_shot_llm(target: str, cfg: dict, seed: int = 0) -> SweepReport:
    return _sample(target, "one_shot_llm")


def run_hidden_checks(target: str, final_diff: str, cfg: dict) -> dict:
    return {"available": True, "applied": True, "behavior_changed": False}


def summarize(report: SweepReport, hidden: dict | None = None) -> dict:
    return {
        "repo_id": report.repo_id,
        "method": report.method,
        "behavior_changed": (hidden or {}).get("behavior_changed"),
    }
