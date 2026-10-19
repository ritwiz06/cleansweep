from __future__ import annotations

from pathlib import Path

import pandas as pd

from cleansweep.core.io import load_json
from cleansweep.core.models import SweepReport

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "sample_report.json"


def find_reports(raw_dir: str | Path = ROOT / "results" / "raw") -> list[Path]:
    """Saved sweep reports, newest first; the sample report if there are none yet."""
    found = sorted(Path(raw_dir).rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return found or [SAMPLE]


def load_report(path: str | Path) -> SweepReport:
    return load_json(SweepReport, path)


def plan_table(report: SweepReport) -> pd.DataFrame:
    """One row per plan item with its Guard status."""
    status = {r.item_id: r.status for r in report.results}
    rows = [
        {
            "status": status.get(i.item_id, "-"),
            "lane": i.lane,
            "category": i.category,
            "unit": i.unit.key,
            "reason": i.reason,
            "evidence": "; ".join(i.evidence),
            "safe_score": i.safe_score,
            "item_id": i.item_id,
        }
        for i in report.plan.items
    ]
    return pd.DataFrame(rows)


def slop_meter(report: SweepReport) -> dict:
    """Items cleaned vs. still open (rolled back or only suggested)."""
    status = [r.status for r in report.results]
    cleaned = status.count("kept") + status.count("repaired")
    return {
        "cleaned": cleaned,
        "open": len(report.plan.items) - cleaned,
        "lines_removed": report.stats.get("lines_removed", 0),
    }


def restore_command(evidence: list[str], unit_path: str) -> str | None:
    """Shell command to bring back a quarantined file, if the item deleted one."""
    for line in evidence:
        if line.startswith("quarantined at "):
            return f"cp '{line.removeprefix('quarantined at ')}' '{unit_path}'"
    return None
