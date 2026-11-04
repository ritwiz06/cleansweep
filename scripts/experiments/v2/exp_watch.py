"""Watch mode experiments: the demo (watch the demo app, then its feature patch lands as a new
commit) and the simulated watch over the AIDev histories, next to the v1 Scheduler replay.

    python scripts/experiments/v2/exp_watch.py demo [--no-llm] [--budget-tests 60]
    python scripts/experiments/v2/exp_watch.py simulate [--repos owner/name ...]

demo: prepares the demo app as a fresh git repository (demo/prepare_demo.sh), polls it once,
commits demo/feature.patch, polls again; each poll decides with its reason and a "clean" runs
`clean` on a copy of the commit. Writes results/raw/watch_demo/ (watch_log.jsonl, the clean
runs). simulate: replays each kept repository's history (the same 300 commits and cached slop
measurements as v1's Scheduler replay) under the watch rule, with no test budget and (where the
v1 adaptive policy swept) with the test runs it spent, and writes
results/summary/v2/watch_replay.csv with the v1 policies' rows from
results/summary/v1/scheduler_replay.csv beside them. The watch counts a clean's real cost (three
baseline runs, one per package of four items, the final suite); v1's replay counted one run per
sweep plus one per batch of eight.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from cleansweep.agents import clean_project, watch  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.data import load_history, load_repos  # noqa: E402
from cleansweep.sandbox.cleanup import on_start  # noqa: E402

RAW = ROOT / "results" / "raw" / "watch_demo"
V1 = ROOT / "results" / "summary" / "v1" / "scheduler_replay.csv"
OUT = ROOT / "results" / "summary" / "v2" / "watch_replay.csv"
FIELDS = [
    "repo",
    "policy",
    "budget_tests",
    "commits",
    "measured_commits",
    "sweeps",
    "test_runs_est",
    "slop_debt",
    "slop_debt_per_commit",
    "final_slop",
    "removed",
]
GIT = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]


def demo(use_llm: bool, budget_tests: int) -> Path:
    if RAW.exists():
        shutil.rmtree(RAW)
    RAW.mkdir(parents=True)
    out = subprocess.run(
        ["bash", str(ROOT / "demo" / "prepare_demo.sh"), str(RAW / "repo")],
        capture_output=True,
        text=True,
        check=True,
    )
    repo = Path(out.stdout.strip().splitlines()[-1])
    cfg = load_config()

    def clean(snapshot: str, run: str, test_runs: int | None) -> dict:
        agents = cfg["core"].setdefault("agents", {})
        if test_runs is not None:
            agents["budget"] = {**agents.get("budget", {}), "test_runs": test_runs}
        return clean_project(snapshot, cfg, out=run, use_llm=use_llm)

    w = watch.Watch(str(repo), str(RAW / "watch"), budget_tests=budget_tests)
    for entry in [w.poll(clean)]:
        print(f"{entry['decision']}: {entry['reason']}", flush=True)
    patch = ROOT / "demo" / "feature.patch"
    subprocess.run(["git", "apply", str(patch)], cwd=repo, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "Add the restock feature"], cwd=repo, check=True)
    entry = w.poll(clean)
    print(f"{entry['decision']}: {entry['reason']}", flush=True)
    return RAW / "watch" / "watch_log.jsonl"


def simulate(repos: list[str] | None) -> Path:
    cfg = load_config()
    sim_cfg = {
        **cfg["exp"].get("scheduler", {}),
        "batch_max_size": cfg["exp"].get("batch_max_size", 8),
        "slop_cache": cfg["data"]["aidev"].get("slop_cache", "data/processed/aidev_slop"),
    }
    with V1.open() as f:
        v1 = list(csv.DictReader(f))
    rows = []
    for repo in load_repos():
        name = repo.repo_id.removeprefix("aidev:")
        theirs = [r for r in v1 if r["repo"] == name]
        if (repos and name not in repos) or not theirs:
            continue  # the same repositories as the v1 replay
        t0 = time.time()
        history = load_history(repo)
        adaptive = next((r for r in theirs if r["policy"] == "adaptive"), None)
        spent = int(adaptive["test_runs_est"] or 0) if adaptive else 0
        budgets = [0] + ([spent] if spent else [])  # no cap; the test runs adaptive spent
        for budget in budgets:
            res = watch.simulate_watch(history, repo.local_path, budget, sim_cfg)
            policy = "watch" if budget == 0 else "watch (adaptive's test runs)"
            rows.append(
                {
                    **{k: res.get(k, "") for k in FIELDS},
                    "repo": name,
                    "policy": policy,
                    "budget_tests": budget,
                }
            )
        rows += [{**{k: r.get(k, "") for k in FIELDS}, "budget_tests": ""} for r in theirs]
        print(f"{name}: {len(history)} commits, {time.time() - t0:.0f}s", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return OUT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["demo", "simulate"])
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--budget-tests", type=int, default=60)
    parser.add_argument("--repos", nargs="*")
    args = parser.parse_args(argv)
    on_start()
    if args.what == "demo":
        print(demo(not args.no_llm, args.budget_tests))
    else:
        print(simulate(args.repos))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
