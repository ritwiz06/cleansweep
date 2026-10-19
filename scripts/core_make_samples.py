"""Write tests/fixtures/sample_plan.json and sample_report.json from a real toy-repo sweep.

Also forces the getattr trap (commands.cmd_export) through the Guard so the sample report
contains a rolled-back edit next to the kept ones.
"""

from __future__ import annotations

import copy
from pathlib import Path

from cleansweep.core.config import load_config
from cleansweep.core.io import save_json
from cleansweep.guard import Guard
from cleansweep.sandbox import open_workspace
from cleansweep.workflow import run_sweep

ROOT = Path(__file__).resolve().parents[1]
TOY = ROOT / "tests" / "fixtures" / "toy_repo"


def main() -> None:
    cfg = load_config()
    cfg["core"]["llm"]["enabled"] = False
    report = run_sweep(str(TOY), cfg, method="cleansweep", seed=0)

    trap = next(i for i in report.plan.items if i.unit.key.endswith("commands.py::cmd_export"))
    forced = copy.deepcopy(trap)
    forced.lane = "safe"
    with open_workspace(str(TOY), cfg["core"]["sandbox"]) as ws:
        guard = Guard(ws, None, cfg["core"]["guard"])
        guard.check_batch([forced])
        result = guard.results()[0]
    result.notes = "forced through the Guard for the sample: " + result.notes
    report.results = [r for r in report.results if r.item_id != trap.item_id] + [result]
    report.stats["items_rolled_back"] = 1
    report.started_at = report.finished_at = "2026-10-19T12:00:00+00:00"
    report.plan.created_at = report.started_at

    fixtures = ROOT / "tests" / "fixtures"
    save_json(report.plan, fixtures / "sample_plan.json")
    save_json(report, fixtures / "sample_report.json")
    print(f"wrote {len(report.plan.items)} items, {len(report.results)} results")


if __name__ == "__main__":
    main()
