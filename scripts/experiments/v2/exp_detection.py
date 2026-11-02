"""Detection by category on AIDev, v2 next to v1: what the detectors flag in the files that
reviewers commented on, against the units the reviewers asked agents to remove.

    python scripts/experiments/v2/exp_detection.py [--hours 2]

For every commented commit v1's mining processed (data/processed/aidev_detection.parquet and the
labels of data_aidev_mine.py), the commit is extracted from its clone (files are parsed, never
run) and the v2 line-level detectors (unused variables, debug leftovers, commented-out code,
TODO notes, redundant checks) run on the commented files; each line item counts for the
innermost function or class around it, as a review comment does. v2's Auditor flags v1's units
plus these. Writes results/summary/v2/detection.csv: requested, flagged, both, precision and
recall for v1 and v2, overall, per requested category and per flagged category, on the commits
both cover. The Investigator's verdicts (an LLM step per candidate) are not part of this.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parents[1] / "data"))
sys.path.insert(0, str(HERE.parent / "v1"))

from data_aidev_mine import LFS_OFF, _units_at  # noqa: E402
from exp_reviewer_detection import score  # noqa: E402

from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.data import load_removal_labels  # noqa: E402
from cleansweep.data.swebench import data_path  # noqa: E402
from cleansweep.reviewer.lines import run_line_detectors  # noqa: E402

OUT = ROOT / "results" / "summary" / "v2" / "detection.csv"


def enclosing(units: list[tuple], line: int) -> str | None:
    """The innermost function or class around a line."""
    hits = [u for u in units if u[1] <= line <= u[2]]
    return min(hits, key=lambda u: u[2] - u[1])[0] if hits else None


def line_flags(clone: Path, commit: str, paths: set[str]) -> list[tuple[str, str]] | None:
    """(unit key, category) for the line items in the commented files at a commit; None when
    the commit can't be extracted."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.Popen(
            ["git", *LFS_OFF, "archive", commit],
            cwd=clone,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["tar", "-xf", "-", "-C", tmp], stdin=archive.stdout, capture_output=True)
        if archive.wait() != 0:
            return None
        present = sorted(p for p in paths if (Path(tmp) / p).is_file() and p.endswith(".py"))
        out = []
        for item in run_line_detectors(tmp, present):
            text = (Path(tmp) / item.unit.path).read_text(errors="replace")
            name = enclosing(_units_at(text), item.unit.start_line or 0)
            if name:
                out.append((f"{item.unit.path}::{name}", item.category))
        return out


def rows_for(label: str, requested: pd.DataFrame, flagged: pd.DataFrame) -> list[dict]:
    def key(df):
        return set(zip(df.repo_id, df.unit_key, strict=True))

    base = {"detectors": label, "pull_requests": requested.pr_number.nunique()}
    out = [{**base, "scope": "all categories", **score(key(requested), key(flagged))}]
    for category in sorted(set(requested.category) - {""}):
        part = requested[requested.category == category]
        out.append({**base, "scope": f"requests: {category}", **score(key(part), key(flagged))})
    for category in sorted(set(flagged.category)):
        part = flagged[flagged.category == category]
        out.append({**base, "scope": f"flagged: {category}", **score(key(requested), key(part))})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=float, default=2.0)
    args = parser.parse_args(argv)
    cfg = load_config()["data"]["aidev"]
    clones = data_path(cfg["clones"])
    labels = load_removal_labels()
    v1 = pd.read_parquet(data_path("data/processed/aidev_detection.parquet"))
    commits = v1[["repo_id", "pr_number", "commit_id"]].drop_duplicates()
    requests = pd.read_parquet(data_path("data/processed/aidev_requests.parquet"))
    requests = requests[requests.removal == True]  # noqa: E712
    deadline = time.time() + args.hours * 3600
    added, done = [], []
    for row in commits.itertuples():
        if time.time() > deadline:
            break
        repo = row.repo_id.removeprefix("aidev:")
        paths = set(requests[(requests.repo == repo) & (requests.commit_id == row.commit_id)].path)
        found = line_flags(clones / repo.replace("/", "__"), row.commit_id, paths)
        if found is None:
            continue
        done.append((row.repo_id, row.pr_number, row.commit_id))
        added += [
            {
                "repo_id": row.repo_id,
                "pr_number": row.pr_number,
                "commit_id": row.commit_id,
                "unit_key": k,
                "category": c,
            }
            for k, c in found
        ]
    covered = pd.DataFrame(done, columns=["repo_id", "pr_number", "commit_id"])
    prs = set(zip(covered.repo_id, covered.pr_number, strict=True))
    req = labels[labels.label == 1].copy()
    req["commit_id"] = [
        "covered" if (r, p) in prs else None
        for r, p in zip(req.repo_id, req.pr_number, strict=True)
    ]
    req = req[req.commit_id.notna()]
    v1_flags = v1.merge(covered, on=["repo_id", "pr_number", "commit_id"])
    v2_flags = pd.concat([v1_flags, pd.DataFrame(added)], ignore_index=True)
    rows = rows_for("v1 (static detectors)", req, v1_flags[["repo_id", "unit_key", "category"]])
    rows += rows_for(
        "v2 Auditor (v1 + line-level detectors)", req, v2_flags[["repo_id", "unit_key", "category"]]
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(done)} of {len(commits)} commits; {len(added)} line items; {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
