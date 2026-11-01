"""Reviewer detection against AIDev removal requests (precision and recall).

    python scripts/experiments/v1/exp_reviewer_detection.py

For every labeled commented commit (data_aidev_mine.py labels), compares the units the static
detectors flag in the commented files with the units reviewers asked agents to remove, on the
kept repositories and on all labeled repositories (the kept ones have few review comments).
Writes results/summary/reviewer_detection.csv (overall and per category).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

from cleansweep.core.config import load_config
from cleansweep.data import load_removal_labels
from cleansweep.data.swebench import data_path

ROOT = Path(__file__).resolve().parents[3]


def score(requested: set, flagged: set) -> dict:
    hit = len(requested & flagged)
    return {
        "requested": len(requested),
        "flagged": len(flagged),
        "both": hit,
        "precision": round(hit / len(flagged), 3) if flagged else "",
        "recall": round(hit / len(requested), 3) if requested else "",
    }


def kept_label(kept: int) -> str:
    """ "kept: 20 of 21 runnable repos (1 excluded)" when runnable repos were left out."""
    excluded = int(load_config()["data"]["aidev"].get("excluded_runnable", 0))
    if not excluded:
        return f"kept: {kept} runnable repos"
    return f"kept: {kept} of {kept + excluded} runnable repos ({excluded} excluded)"


def _rows(repos: str, labels: pd.DataFrame, flagged: pd.DataFrame) -> list[dict]:
    req = labels[labels.label == 1]
    key = lambda df: set(zip(df.repo_id, df.unit_key, strict=True))  # noqa: E731
    base = {"repos": repos, "repo_count": labels.repo_id.nunique()}
    rows = [{**base, "scope": "all categories", **score(key(req), key(flagged))}]
    for category in sorted(set(req.category) - {""}):
        rows.append(
            {
                **base,
                "scope": f"requests: {category}",
                **score(key(req[req.category == category]), key(flagged)),
            }
        )
    for category in sorted(set(flagged.get("category", []))):
        rows.append(
            {
                **base,
                "scope": f"flagged: {category}",
                **score(key(req), key(flagged[flagged.category == category])),
            }
        )
    return rows


def main() -> int:
    labels = load_removal_labels()
    det_path = data_path("data/processed/aidev_detection.parquet")
    flagged = pd.read_parquet(det_path) if det_path.exists() else pd.DataFrame(columns=["unit_key"])
    labeled_files = {
        (r, k.split("::")[0]) for r, k in zip(labels.repo_id, labels.unit_key, strict=True)
    }
    flagged = flagged[
        [
            (r, k.split("::")[0]) in labeled_files
            for r, k in zip(flagged.repo_id, flagged.unit_key, strict=True)
        ]
    ]
    kept = {
        f"aidev:{r['full_name']}"
        for r in json.loads(data_path("data/splits/aidev_repos.json").read_text())
    }
    rows = []
    for repos, in_set in (
        (kept_label(len(kept)), lambda df: df.repo_id.isin(kept)),
        ("all labeled", lambda df: df.repo_id == df.repo_id),
    ):
        rows += _rows(repos, labels[in_set(labels)], flagged[in_set(flagged)])
    out = ROOT / "results" / "summary" / "reviewer_detection.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for r in rows:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
