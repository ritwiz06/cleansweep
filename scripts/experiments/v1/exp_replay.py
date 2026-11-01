"""Scheduler replay on the kept AIDev repositories (static detectors only).

    python scripts/experiments/v1/exp_replay.py [--repos owner/name ...] [--points 40]

For every kept repository (data/splits/aidev_repos.json): its history (last 300 first-parent
commits, agent pull requests marked), then simulate() under each policy, plus "none" (never
sweep) for reference. Writes results/summary/v1/scheduler_replay.csv and scheduler_curves.csv.
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from cleansweep.core.config import load_config
from cleansweep.data import load_history, load_repos
from cleansweep.scheduler import simulate

ROOT = Path(__file__).resolve().parents[3]
SUMMARY = ROOT / "results" / "summary" / "v1"
POLICIES = ["none", "every_pr", "every_n", "daily", "adaptive"]
FIELDS = [
    "repo",
    "policy",
    "commits",
    "agent_pr_commits",
    "measured_commits",
    "sweeps",
    "test_runs_est",
    "slop_debt",
    "slop_debt_per_commit",
    "final_slop",
    "removed",
    "resurrected",
    "resurrection_rate",
    "seconds",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repos", nargs="*", help="only these owner/name repositories")
    parser.add_argument("--points", type=int, help="commits to measure per repository")
    args = parser.parse_args(argv)
    cfg = load_config()
    sim_cfg = {
        **cfg["exp"].get("scheduler", {}),
        "batch_max_size": cfg["exp"].get("batch_max_size", 8),
        "slop_cache": cfg["data"]["aidev"].get("slop_cache", "data/processed/aidev_slop"),
    }
    if args.points:
        sim_cfg["replay_points"] = args.points
    rows, curves = [], []
    for repo in load_repos():
        name = repo.repo_id.removeprefix("aidev:")
        if args.repos and name not in args.repos:
            continue
        t0 = time.time()
        history = load_history(repo)
        for policy in POLICIES:
            res = simulate(history, repo.local_path, policy, sim_cfg)
            rows.append(
                {
                    **{k: res.get(k, "") for k in FIELDS},
                    "repo": name,
                    "agent_pr_commits": sum(bool(e.is_agent) for e in history),
                    "seconds": round(time.time() - t0, 1),
                }
            )
            curves += [{"repo": name, "policy": policy, **c} for c in res.get("curve", [])]
        print(
            f"{name}: {len(history)} commits, {rows[-1]['measured_commits']} measured, "
            f"{time.time() - t0:.0f}s",
            flush=True,
        )
    SUMMARY.mkdir(parents=True, exist_ok=True)
    with (SUMMARY / "scheduler_replay.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with (SUMMARY / "scheduler_curves.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["repo", "policy", "index", "sha", "timestamp", "open_slop", "swept", "loc"],
        )
        writer.writeheader()
        writer.writerows(curves)
    print(f"{len(rows)} rows -> results/summary/v1/scheduler_replay.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
