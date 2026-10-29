"""Run SWE-bench patches or AIDev repositories with several methods, then the hidden checks.

    python scripts/exp_swebench.py --tier data/splits/swebench_tier2.json \\
        --out results/raw/swebench_t2 [--methods cleansweep-gatekeeper tools_only ...] [--resume]
        [--hidden-only]
    python scripts/exp_swebench.py --tier data/splits/aidev_repos.json \\
        --out results/raw/aidev_sweeps

Saves one SweepReport per run to <out>/<instance>__<agent>__<method>.json, or for AIDev
<owner>__<name>__<method>.json (hidden-check results and timing under stats["hidden"] and
stats["minutes"]), and appends to <out>/log.txt. AIDev repositories run at their head sha, the
fastest test suite first. A failed run is logged with its traceback in <out>/errors/ and retried
by the next --resume. --hidden-only reruns just the hidden checks of saved reports whose final
diff did not apply. An AIDev run needs the repository's cached history
(data/processed/aidev_history) for its agent scope; without it the detectors would see the whole
repository, so the runner stops before the first run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from cleansweep.core.config import load_config
from cleansweep.core.io import save_json
from cleansweep.data.aidev import agent_history
from cleansweep.eval import run_hidden_checks
from cleansweep.workflow import run_sweep

ROOT = Path(__file__).resolve().parents[1]
# label -> (run_sweep method, judge mode); guard_tests_only uses the advisory judge so that it
# differs from "cleansweep-advisory" only by the probes
METHODS = {
    "cleansweep-gatekeeper": ("cleansweep", "gatekeeper"),
    "cleansweep-advisory": ("cleansweep", "advisory"),
    "guard_tests_only": ("guard_tests_only", "advisory"),
    "tools_only": ("tools_only", None),
    "one_shot_llm": ("one_shot_llm", None),
    "one_shot_retry": ("one_shot_retry", None),
}
# the main comparison; one_shot_retry runs only where asked (the runs whose reply didn't compile)
DEFAULT_METHODS = list(METHODS)[:5]


class Log:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, line: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.path.open("a", encoding="utf-8") as f:
            f.write(f"{stamp} {line}\n")
        print(f"{stamp} {line}", flush=True)


def run_one(target: str, label: str, cfg: dict, path: Path) -> dict:
    method, judge = METHODS[label]
    if judge:
        os.environ["CLEANSWEEP_JUDGE_MODE"] = judge
    else:
        os.environ.pop("CLEANSWEEP_JUDGE_MODE", None)
    t0 = time.time()
    report = run_sweep(target, cfg, method)
    t_sweep = time.time() - t0
    hidden = run_hidden_checks(target, report.stats.get("final_diff", ""), cfg)
    report.stats.update(
        hidden=hidden,
        judge_mode=judge,
        minutes=round((time.time() - t0) / 60, 2),
        sweep_minutes=round(t_sweep / 60, 2),
    )
    save_json(report, path)
    return report.stats


def rerun_hidden(target: str, cfg: dict, path: Path) -> dict | None:
    """Rerun the hidden checks of a saved report whose final diff did not apply; the sweep is
    not rerun. None if the report's hidden checks already ran."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data["stats"].get("hidden") or {}).get("applied") is not False:
        return None
    hidden = {**run_hidden_checks(target, data["stats"].get("final_diff", ""), cfg), "rerun": True}
    data["stats"]["hidden"] = hidden
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return hidden


def missing_history(jobs: list[tuple[str, str]]) -> list[str]:
    """AIDev repositories in jobs without a cached history (no agent scope possible)."""
    names = [t.removeprefix("aidev:").partition("@")[0] for t, _ in jobs if t.startswith("aidev:")]
    return [n for n in names if agent_history(n)[1] is None]


def targets(entries: list[dict]) -> list[tuple[str, str]]:
    """(target, report name prefix) for SWE-bench split entries or AIDev repository entries."""
    out = []
    if entries and "full_name" in entries[0]:
        for e in sorted(entries, key=lambda e: (int(e.get("test_seconds") or 0), e["full_name"])):
            out.append(
                (f"aidev:{e['full_name']}@{e['head_sha']}", e["full_name"].replace("/", "__"))
            )
        return out
    return [
        (f"swebench:{e['instance_id']}:{e['agent']}", f"{e['instance_id']}__{e['agent']}")
        for e in entries
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--tier", required=True, help="split file, e.g. data/splits/swebench_tier2.json"
    )
    parser.add_argument("--out", required=True, help="output folder, e.g. results/raw/swebench_t2")
    parser.add_argument("--methods", nargs="+", choices=list(METHODS), default=DEFAULT_METHODS)
    parser.add_argument("--resume", action="store_true", help="skip runs whose report exists")
    parser.add_argument(
        "--hidden-only",
        action="store_true",
        help="only rerun the hidden checks of saved reports whose final diff did not apply",
    )
    args = parser.parse_args(argv)
    out = Path(args.out)
    done = sorted(out.glob("*__*__*.json")) if out.exists() else []
    if done and not (args.resume or args.hidden_only):
        print(f"{out} already has {len(done)} reports; pass --resume to continue", file=sys.stderr)
        return 2
    log = Log(out / "log.txt")
    cfg = load_config()
    jobs = targets(json.loads(Path(args.tier).read_text()))
    missing = [] if args.hidden_only else missing_history(jobs)
    if missing:
        print(f"no cached history for {', '.join(missing)}: link data/processed", file=sys.stderr)
        return 2
    log(f"start: {len(jobs)} targets x {len(args.methods)} methods from {args.tier}")
    for target, prefix in jobs:
        for label in args.methods:
            path = out / f"{prefix}__{label}.json"
            if args.hidden_only:
                hidden = rerun_hidden(target, cfg, path) if path.exists() else None
                if hidden is not None:
                    log(
                        f"hidden {target} {label}: applied {hidden.get('applied')}, "
                        f"changed {hidden.get('behavior_changed')}"
                    )
                continue
            if path.exists():
                continue
            log(f"run {target} {label}")
            t0 = time.time()
            try:
                stats = run_one(target, label, cfg, path)
            except Exception as exc:  # record and move on; --resume retries it
                log(f"error {target} {label}: {type(exc).__name__}: {exc}")
                (out / "errors").mkdir(exist_ok=True)
                (out / "errors" / f"{path.stem}.txt").write_text(traceback.format_exc())
                continue
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
