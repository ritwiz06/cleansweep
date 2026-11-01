"""Print PatchDiff patch counts per agent, per repo and per label, and write the data summaries
the dashboard's Data page reads.

python scripts/data/data_summary.py

Writes results/data_summary/:
- swebench_patchdiff.csv: SWE-bench Verified tasks, PatchDiff patches per agent and label
- tiers.csv: patches, instances, repositories and differing patches per tier split
- aidev_funnel.csv: AIDev-pop repositories down to the runnable ones, then the drop reasons
  (counts only; the full selection file, with the repositories left out of committed files, is
  used when it exists locally)
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from cleansweep.core.config import load_config
from cleansweep.data import load_agent_patches
from cleansweep.data.swebench import data_path, load_rows

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "data_summary"


def _write(name: str, rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / name).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def swebench_patchdiff(tasks: int, patches) -> list[dict]:
    label = {True: "differs", False: "not shown to differ", None: "untested"}
    rows = [{"dataset": "SWE-bench Verified", "group": "tasks", "count": tasks}]
    rows.append({"dataset": "PatchDiff", "group": "plausible patches", "count": len(patches)})
    for key, n in Counter(label[p.differs_from_oracle] for p in patches).most_common():
        rows.append({"dataset": "PatchDiff", "group": f"label: {key}", "count": n})
    for key, n in Counter(p.agent for p in patches).most_common():
        rows.append({"dataset": "PatchDiff", "group": f"agent: {key}", "count": n})
    return rows


def tiers(repos: dict[str, str]) -> list[dict]:
    rows = []
    for path in sorted(data_path("data/splits").glob("swebench_tier*.json")):
        entries = json.loads(path.read_text())
        ids = {e["instance_id"] for e in entries}
        rows.append(
            {
                "tier": path.stem.removeprefix("swebench_"),
                "patches": len(entries),
                "instances": len(ids),
                "repositories": len({repos.get(i, i.split("__")[0]) for i in ids}),
                "differ": sum(bool(e.get("differs_from_oracle")) for e in entries),
            }
        )
    return rows


def aidev_funnel() -> list[dict]:
    from cleansweep.data.aidev import table

    cfg = load_config()["data"]["aidev"]
    repos = table("repository")
    prs = table("pull_request", ("id", "merged_at", "repo_id"))
    merged = prs[prs.merged_at.notna()].groupby("repo_id").size().rename("merged")
    py = repos[(repos.language == "Python") & (~repos.is_forked)].merge(
        merged, left_on="id", right_index=True, how="left"
    )
    qualifying = int((py.merged.fillna(0) >= int(cfg["min_agent_prs"])).sum())
    full = data_path("data/processed/aidev_full/aidev_filter.csv")
    committed = data_path("results/data_summary/aidev_filter.csv")
    rows = list(csv.DictReader((full if full.exists() else committed).open()))
    kept = sum(r["status"] == "kept" for r in rows)
    excluded = int(cfg.get("excluded_runnable", 0))
    in_files = sum(r["status"] == "kept" for r in csv.DictReader(committed.open()))
    out = [
        {"stage": "AIDev-pop repositories", "count": len(repos), "note": ""},
        {"stage": "Python, not a fork", "count": len(py), "note": ""},
        {
            "stage": f"at least {cfg['min_agent_prs']} merged agent PRs",
            "count": qualifying,
            "note": "",
        },
        {"stage": "sampled (seeded)", "count": len(rows), "note": f"seed {cfg['seed']}"},
        {
            "stage": "runnable",
            "count": kept,
            "note": f">= {cfg['min_tests']} tests, >= {cfg['min_pass_rate']:.0%} passing, "
            f"< {int(cfg['max_test_seconds']) // 60} min",
        },
        {
            "stage": "in committed files",
            "count": in_files,
            "note": f"{excluded} left out of the released data files" if excluded else "",
        },
    ]
    for reason, n in Counter(r["reason"] for r in rows if r["status"] != "kept").most_common():
        out.append({"stage": f"dropped: {reason}", "count": n, "note": ""})
    return out


def main() -> int:
    rows = load_rows()
    repos = {r["instance_id"]: r["repo"] for r in rows}
    patches = load_agent_patches()
    print(f"{len(patches)} plausible patches")
    for title, counts in (
        ("per agent", Counter(p.agent for p in patches)),
        ("per repo", Counter(repos.get(p.instance_id, "?") for p in patches)),
        ("per label (differs_from_oracle)", Counter(str(p.differs_from_oracle) for p in patches)),
    ):
        print(f"\n{title}:")
        for key, n in counts.most_common():
            print(f"  {key:30} {n}")
    _write("swebench_patchdiff.csv", swebench_patchdiff(len(rows), patches))
    _write("tiers.csv", tiers(repos))
    _write("aidev_funnel.csv", aidev_funnel())
    print(f"\nwrote swebench_patchdiff.csv, tiers.csv, aidev_funnel.csv to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
