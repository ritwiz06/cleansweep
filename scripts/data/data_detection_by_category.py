"""Reviewer detection by kind of removal request: where the detectors match what reviewers ask.

    python scripts/data/data_detection_by_category.py

Each confirmed removal request gets its taxonomy cluster (the same fit as aidev_taxonomy.csv),
and each cluster is mapped to the detector category most of its requests have (unused_import,
dead_code, duplicate, leftover_file, wrapper, other). Requested units are the labeled units
reviewers asked to remove; flagged units are what the static detectors report in the same
commented files (data_aidev_mine.py labels). Writes results/data_summary/detection_by_category.csv
with one row per cluster and one per detector category:
- recall: requested units that the mapped category's detector flags
- recall_any_detector: requested units that any detector flags
- precision: flagged units of the mapped category, in that cluster's files, that were requested
- flagged_as: the detector categories that flag the requested units (often not the mapped one)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cleansweep.data import load_removal_labels
from cleansweep.data.swebench import data_path
from cleansweep.mining.taxonomy import assign_clusters, build_taxonomy

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "data_summary" / "detection_by_category.csv"
DETECTOR_CATEGORIES = ["unused_import", "dead_code", "duplicate", "leftover_file", "wrapper"]


def detector_category(category) -> str:
    return category if category in DETECTOR_CATEGORIES else "other"


def _file(repo_id: str, pr: int, unit_key: str) -> str:
    return f"{repo_id}#{int(pr)}#{unit_key.split('::')[0]}"


def _ratio(a: int, b: int):
    return round(a / b, 3) if b else ""


def main() -> int:
    req = pd.read_parquet(data_path("data/processed/aidev_requests.parquet"))
    req = req[req.removal == True].copy()  # noqa: E712 (pandas mask)
    req["cluster"] = assign_clusters(req)
    req["kind"] = req.category.map(detector_category)
    req["repo_id"] = "aidev:" + req.repo
    taxonomy = build_taxonomy(req).set_index("cluster")
    mapped = req.groupby("cluster").kind.agg(lambda s: s.value_counts().index[0])

    labels = load_removal_labels()
    wanted = labels[labels.label == 1].copy()
    wanted["kind"] = wanted.category.map(detector_category)

    # a requested unit's cluster: its file's requests of the same kind, else any of its file's
    by_file_kind = req.groupby(["repo_id", "pr_number", "path", "kind"]).cluster.agg(
        lambda s: s.value_counts().index[0]
    )
    by_file = req.groupby(["repo_id", "pr_number", "path"]).cluster.agg(
        lambda s: s.value_counts().index[0]
    )

    def cluster_of(row) -> int | None:
        repo, pr, path = row.repo_id, int(row.pr_number), row.unit_key.split("::")[0]
        if (repo, pr, path, row.kind) in by_file_kind.index:
            return int(by_file_kind[(repo, pr, path, row.kind)])
        return int(by_file[(repo, pr, path)]) if (repo, pr, path) in by_file.index else None

    wanted["cluster"] = [cluster_of(r) for r in wanted.itertuples()]

    labeled_files = {
        _file(r, p, k)
        for r, p, k in zip(labels.repo_id, labels.pr_number, labels.unit_key, strict=True)
    }
    det_path = data_path("data/processed/aidev_detection.parquet")
    flagged = pd.read_parquet(det_path)
    flagged = flagged[
        [
            _file(r, p, k) in labeled_files
            for r, p, k in zip(flagged.repo_id, flagged.pr_number, flagged.unit_key, strict=True)
        ]
    ]
    flagged = flagged.assign(
        kind=flagged.category.map(detector_category),
        file=[
            _file(r, p, k)
            for r, p, k in zip(flagged.repo_id, flagged.pr_number, flagged.unit_key, strict=True)
        ],
    )
    flagged_any = set(zip(flagged.repo_id, flagged.unit_key, strict=True))
    kinds_of: dict[tuple, set] = {}
    for r, k, kind in zip(flagged.repo_id, flagged.unit_key, flagged.kind, strict=True):
        kinds_of.setdefault((r, k), set()).add(kind)

    def flagged_as(asked: set) -> str:
        """Which detector categories flag the requested units, e.g. "duplicate 5, dead_code 1"."""
        counts = pd.Series([k for u in asked for k in sorted(kinds_of.get(u, ()))]).value_counts()
        return ", ".join(f"{k} {n}" for k, n in counts.items())

    def units(df: pd.DataFrame) -> set:
        return set(zip(df.repo_id, df.unit_key, strict=True))

    rows = []
    for cluster in sorted(req.cluster.unique()):
        kind = mapped[cluster]
        part = req[req.cluster == cluster]
        files = {
            _file(r, p, f) for r, p, f in zip(part.repo_id, part.pr_number, part.path, strict=True)
        }
        asked = units(wanted[wanted.cluster == cluster])
        same = flagged[(flagged.kind == kind) & flagged.file.isin(files)]
        found = units(same)
        rows.append(
            {
                "level": "cluster",
                "cluster": int(cluster),
                "top_terms": taxonomy.loc[cluster, "top_terms"],
                "mapped_category": kind,
                "requests": int((req.cluster == cluster).sum()),
                "requested_units": len(asked),
                "flagged_units": len(found),
                "both": len(asked & found),
                "precision": _ratio(len(asked & found), len(found)),
                "recall": _ratio(len(asked & found), len(asked)),
                "recall_any_detector": _ratio(len(asked & flagged_any), len(asked)),
                "flagged_as": flagged_as(asked),
            }
        )
    for kind in [*DETECTOR_CATEGORIES, "other"]:
        asked = units(wanted[wanted.kind == kind])
        found = units(flagged[flagged.kind == kind])
        rows.append(
            {
                "level": "category",
                "cluster": "",
                "top_terms": "",
                "mapped_category": kind,
                "requests": int((req.kind == kind).sum()),
                "requested_units": len(asked),
                "flagged_units": len(found),
                "both": len(asked & found),
                "precision": _ratio(len(asked & found), len(found)),
                "recall": _ratio(len(asked & found), len(asked)),
                "recall_any_detector": _ratio(len(asked & flagged_any), len(asked)),
                "flagged_as": flagged_as(asked),
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(pd.DataFrame(rows).drop(columns=["top_terms"]).to_string(index=False))
    unplaced = int(wanted.cluster.isna().sum())
    print(f"{len(wanted)} requested units ({unplaced} without a matching request)")
    print(f"-> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
