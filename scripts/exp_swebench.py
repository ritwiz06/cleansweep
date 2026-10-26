"""Run SWE-bench Tier 1: every patch with every method, then the hidden checks.

    python scripts/exp_swebench_tier1.py [--tier data/splits/swebench_tier1.json] [--only METHOD]

Saves one SweepReport per run to results/raw/swebench_t1/<instance>__<agent>__<method>.json
(hidden-check results and timing under stats["hidden"] and stats["minutes"]) and appends to
run.log in the same folder. Runs one after another; a finished run is skipped when restarted.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

from cleansweep.core.config import load_config
from cleansweep.core.io import save_json
from cleansweep.eval import run_hidden_checks
from cleansweep.workflow import run_sweep

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "raw" / "swebench_t1"
# label -> (run_sweep method, judge mode); guard_tests_only uses the advisory judge so that it
# differs from "cleansweep-advisory" only by the probes
METHODS = {
    "cleansweep-gatekeeper": ("cleansweep", "gatekeeper"),
    "cleansweep-advisory": ("cleansweep", "advisory"),
    "tools_only": ("tools_only", None),
    "guard_tests_only": ("guard_tests_only", "advisory"),
}


def log(line: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (OUT / "run.log").open("a", encoding="utf-8") as f:
        f.write(f"{stamp} {line}\n")
    print(f"{stamp} {line}", flush=True)


def run_one(target: str, label: str, cfg: dict, path: Path) -> None:
    method, judge = METHODS[label]
    if judge:
        os.environ["CLEANSWEEP_JUDGE_MODE"] = judge
    else:
        os.environ.pop("CLEANSWEEP_JUDGE_MODE", None)
    t0 = time.time()
    report = run_sweep(target, cfg, method)
    t_sweep = time.time() - t0
    hidden = run_hidden_checks(target, report.stats.get("final_diff", ""), cfg)
    report.stats["hidden"] = hidden
    report.stats["judge_mode"] = judge
    report.stats["minutes"] = round((time.time() - t0) / 60, 2)
    report.stats["sweep_minutes"] = round(t_sweep / 60, 2)
    save_json(report, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tier", default=str(ROOT / "data" / "splits" / "swebench_tier1.json"))
    parser.add_argument("--only", choices=list(METHODS), action="append")
    args = parser.parse_args(argv)
    cfg = load_config()
    patches = json.loads(Path(args.tier).read_text())
    labels = args.only or list(METHODS)
    log(f"start: {len(patches)} patches x {len(labels)} methods")
    for entry in patches:
        target = f"swebench:{entry['instance_id']}:{entry['agent']}"
        for label in labels:
            path = OUT / f"{entry['instance_id']}__{entry['agent']}__{label}.json"
            if path.exists():
                continue
            log(f"run {target} {label}")
            t0 = time.time()
            try:
                run_one(target, label, cfg, path)
            except Exception as exc:  # record and move on; a restart retries it
                log(f"error {target} {label}: {type(exc).__name__}: {exc}")
                (OUT / "errors").mkdir(exist_ok=True)
                (OUT / "errors" / f"{path.stem}.txt").write_text(traceback.format_exc())
                continue
            stats = json.loads(path.read_text())["stats"]
            hidden = stats["hidden"]
            log(
                f"done {target} {label} in {time.time() - t0:.0f}s: kept {stats['items_kept']}, "
                f"rolled back {stats['items_rolled_back']}, test runs {stats['test_runs']}, "
                f"hidden changed {hidden.get('behavior_changed')}"
            )
    log("finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
