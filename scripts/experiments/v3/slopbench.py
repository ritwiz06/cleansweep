"""SlopBench: the slop-injection benchmark as a list of repositories at commits, never their code.

    python scripts/experiments/v3/slopbench.py list

Writes results/summary/v3/slopbench_repos.csv: every repository the injection benchmark plants
into (v2's set, seeds 1-3, and v3's out-of-sample set, seed 4), with its commit, license, clone
URL and seeds. With the plant code (scripts/experiments/v2/exp_inject.py: `inject`, the plant
checks in `check_plants`, the hidden test) and the v3 wrapper (exp_inject_v3.py), anyone can
rebuild the benchmark from these commits; no third-party code is copied here. The data card is
docs/slopbench.md. The v3 set is the one the runs settled (results/summary/v3/sets.csv, from
exp_tables_v3.py: the split's set with unusable repositories replaced from the reserve), or the
split's set before any run.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "results" / "summary" / "v3" / "slopbench_repos.csv"
FIELDS = ["repo", "set", "seeds", "commit", "license", "clone_url", "replaces"]


def _inject_v2():
    path = ROOT / "scripts" / "experiments" / "v2" / "exp_inject.py"
    spec = importlib.util.spec_from_file_location("exp_inject_v2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(
    v2_repos: list[str],
    v2_split: list[dict],
    v3_split: dict,
    pool: list[dict],
    settled: list[dict] | None = None,
) -> list[dict]:
    """One row per benchmark repository (the toy fixture is in this repository and left out)."""
    licenses = {r["full_name"]: r["license"] for r in pool if r["license"] not in ("", "nan")}
    heads = {r["full_name"]: r for r in v2_split}
    v3 = {r["full_name"]: r for r in v3_split["inject"] + v3_split.get("reserve", [])}
    settled = settled or [{"repo": r["full_name"]} for r in v3_split["inject"]]
    out = []
    for repo in v2_repos:
        if repo == "toy":
            continue
        r = heads[repo]
        out.append(
            {
                "repo": repo,
                "set": "v2",
                "seeds": "1 2 3",
                "commit": r["head_sha"],
                "license": licenses.get(repo, "none detected"),
                "clone_url": r["clone_url"],
                "replaces": "",
            }
        )
    for row in settled:
        r = v3[row["repo"]]
        out.append(
            {
                "repo": r["full_name"],
                "set": "v3 (out of sample)",
                "seeds": "4",
                "commit": r["head_sha"],
                "license": r["license"],
                "clone_url": r["clone_url"],
                "replaces": f"{row['replaces']} ({row['reason']})" if row.get("replaces") else "",
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["list"])
    parser.parse_args(argv)
    sets = ROOT / "results" / "summary" / "v3" / "sets.csv"
    settled = None
    if sets.exists():
        with sets.open() as f:
            settled = [r for r in csv.DictReader(f) if r["set"] == "INJECT"]
    v2_split = json.loads((ROOT / "data" / "splits" / "aidev_repos.json").read_text())
    v3_split = json.loads((ROOT / "data" / "splits" / "v3_repos.json").read_text())
    with (ROOT / "results" / "data_summary" / "v3_repo_pool.csv").open() as f:
        pool = list(csv.DictReader(f))
    out = rows(_inject_v2().REPOS, v2_split, v3_split, pool, settled)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out)
    print(f"{len(out)} repositories -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
