from __future__ import annotations

from pathlib import Path

from cleansweep.core.io import load_json
from cleansweep.core.models import SweepReport

SAMPLE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sample_report.json"


def run_sweep(target: str, cfg: dict, method: str = "cleansweep", seed: int = 0) -> SweepReport:
    report = load_json(SweepReport, SAMPLE)
    report.repo_id = report.plan.repo_id = f"local:{Path(target).name}"
    report.method, report.seed = method, seed
    return report
