"""Merge the toy, demo, SWE-bench Tier 1 and Tier 2 runs into results/summary/main_results.csv.

    python scripts/exp_collect.py [--t2 ../cleansweep-runs/results/raw/swebench_t2]

One row per (target, method). Toy and demo rows come from the recorded live runs listed in
LOCAL_RUNS (probes era, 2026-10-26); SWE-bench rows from the runners' report files.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.live_runner import fold, read_events  # noqa: E402
from app.loaders import outcome_score  # noqa: E402
from cleansweep.core.io import load_json  # noqa: E402
from cleansweep.core.models import SweepReport  # noqa: E402

RAW = ROOT / "results" / "raw"
OUT = ROOT / "results" / "summary" / "main_results.csv"
LOCAL_RUNS = {
    "toy": "tests/fixtures/toy_repo",
    "demo": ".cleansweep/demo/shop_app",
}
FIELDS = [
    "target_set",
    "target",
    "method",
    "edits_applied",
    "lines_removed",
    "files_removed",
    "test_runs",
    "hidden_changed",
    "llm_calls",
    "minutes",
    "outcome_hits",
    "outcome_total",
    "invalid_output",
]
OUTCOMES = ("edits_applied", "lines_removed", "files_removed", "hidden_changed")


def _invalid(row: dict, stats: dict) -> dict:
    """A one-shot reply that didn't parse is not "0 edits": its outcomes are left empty."""
    bad = int(stats.get("invalid_output", 0))
    return {**row, **dict.fromkeys(OUTCOMES, "")} | {"invalid_output": bad} if bad else row


def label(method: str, judge_mode: str | None) -> str:
    return f"cleansweep-{judge_mode}" if method == "cleansweep" else method


def _applied(results) -> int:
    get = (lambda r, k: r[k]) if results and isinstance(results[0], dict) else getattr
    return sum(
        get(r, "status") in ("kept", "repaired") and bool(get(r, "diff").strip()) for r in results
    )


def local_rows() -> list[dict]:
    rows = []
    for run_dir in sorted((RAW / "live").glob("2026102[6-9]_*")):
        if not (run_dir / "report.json").exists():
            continue
        state = fold(read_events(run_dir / "events.jsonl"))
        run = state["run"]
        target_set = next(
            (k for k, v in LOCAL_RUNS.items() if run["target"].rstrip("/") == v), None
        )
        if target_set is None:
            continue
        report = load_json(SweepReport, run_dir / "report.json")
        key = ROOT / (LOCAL_RUNS[target_set] + "_expected.json")
        score = outcome_score(report, key) if key.exists() else None
        stats = report.stats
        row = {
            "target_set": target_set,
            "target": run_dir.name,
            "method": label(run["method"], run.get("judge_mode")),
            "edits_applied": _applied(report.results),
            "lines_removed": stats["lines_removed"],
            "files_removed": stats["files_removed"],
            "test_runs": stats["test_runs"],
            "hidden_changed": int(bool((state["hidden"] or {}).get("behavior_changed"))),
            "llm_calls": stats["llm_calls"],
            "minutes": round(stats["wall_seconds"] / 60, 2),
            "outcome_hits": score["hits"] if score else "",
            "outcome_total": score["total"] if score else "",
            "invalid_output": 0,
        }
        rows.append(_invalid(row, stats))
    return rows


def swebench_rows(folder: Path, target_set: str) -> list[dict]:
    rows = []
    for path in sorted(folder.glob("*__*__*.json")):
        instance, agent, method = path.stem.rsplit("__", 2)
        data = json.loads(path.read_text())
        stats = data["stats"]
        row = {
            "target_set": target_set,
            "target": f"{instance}__{agent}",
            "method": method,
            "edits_applied": _applied(data["results"]),
            "lines_removed": stats["lines_removed"],
            "files_removed": stats["files_removed"],
            "test_runs": stats["test_runs"],
            "hidden_changed": int(bool(stats["hidden"].get("behavior_changed"))),
            "llm_calls": stats["llm_calls"],
            "minutes": stats["minutes"],
            "outcome_hits": "",
            "outcome_total": "",
            "invalid_output": 0,
        }
        rows.append(_invalid(row, stats))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--t1", default=str(RAW / "swebench_t1"))
    parser.add_argument(
        "--t2", default=str(ROOT.parent / "cleansweep-runs" / "results" / "raw" / "swebench_t2")
    )
    parser.add_argument(
        "--t2-oneshot",
        default=str(ROOT.parent / "cleansweep-runs-2" / "results" / "raw" / "swebench_t2_oneshot"),
        help="one_shot_llm reruns on Tier 2; preferred over the first run's one_shot_llm rows",
    )
    args = parser.parse_args(argv)
    rows = local_rows() + swebench_rows(Path(args.t1), "swebench_t1")
    t2 = swebench_rows(Path(args.t2), "swebench_t2") if Path(args.t2).exists() else []
    if Path(args.t2_oneshot).exists():
        rerun = [r for r in swebench_rows(Path(args.t2_oneshot), "swebench_t2")]
        redone = {r["target"] for r in rerun if r["method"] == "one_shot_llm"}
        t2 = [r for r in t2 if not (r["method"] == "one_shot_llm" and r["target"] in redone)]
        t2 += [r for r in rerun if r["method"] == "one_shot_llm"]
    rows += t2
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["target_set"]] = counts.get(r["target_set"], 0) + 1
    print(f"{OUT.relative_to(ROOT)}: {len(rows)} rows {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
