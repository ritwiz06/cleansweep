"""Collect the v2 evaluation runs into one per-run CSV, next to v1's gatekeeper runs on the
same SWE-bench and AIDev targets, measured the same way.

    python scripts/experiments/v2/exp_collect_v2.py [--raw results/raw/v2_eval]

Reads the reports exp_eval.py wrote in <raw>/{toy_demo,tier1,tier2,aidev}/. On the toy repo and
the demo app, v1's methods ran in the same harness. On SWE-bench and AIDev, v1's run is the
gatekeeper report that results/summary/v1/main_results.csv counts (exp_collect.py's folders,
first folder wins); it is measured from its report as exp_eval.py measures v2's, and a report
whose lines removed differ from main_results.csv stops the script. Its hidden result is
main_results.csv's (flaky or overload-suspect: no outcome). Hidden changes are then marked
flaky as in exp_collect.py: another run on the target made the same final diff and its hidden
checks did not change. Writes results/summary/v2/eval_runs.csv.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "v1"))

from archive_paths import aidev_folders, archived  # noqa: E402
from exp_collect import _digest, _scope_kind, mark_flaky  # noqa: E402
from exp_eval import FIELDS, measures  # noqa: E402

from cleansweep.core.io import load_json  # noqa: E402
from cleansweep.core.models import SweepReport  # noqa: E402

OUT = ROOT / "results" / "summary" / "v2" / "eval_runs.csv"
V1_RESULTS = ROOT / "results" / "summary" / "v1" / "main_results.csv"
V1 = "cleansweep-gatekeeper"
# exp_eval.py output folder -> target set (toy and demo pool as "answer keys", as in v1)
SETS = {"toy_demo": "answer keys", "tier1": "swebench_t1", "tier2": "swebench_t2", "aidev": "aidev"}


def v1_folders(target_set: str) -> list[Path]:
    """The folders exp_collect.py reads v1's reports from, in its order."""
    if target_set == "swebench_t1":
        return [ROOT / "results" / "raw" / "swebench_t1"]
    if target_set == "swebench_t2":
        return [
            archived("cleansweep-runs", "swebench_t2"),
            archived("cleansweep-runs-2", "swebench_t2_rerun"),
        ]
    return aidev_folders()


def hidden_value(hidden: dict) -> int | str:
    """1 or 0, or "" when the hidden checks had no outcome."""
    if not hidden.get("available", True) or hidden.get("applied") is False:
        return ""
    return int(bool(hidden.get("behavior_changed")))


def row_for(target_set: str, report: SweepReport, name: str, label: str, repeat: int) -> dict:
    s = report.stats
    hidden = s.get("hidden") or {}
    row = measures(name, label, repeat, report, hidden, s.get("score") or {})
    row["hidden_changed"] = hidden_value(hidden)
    return {
        "target_set": target_set,
        **row,
        "_group": name,
        "_diff": _digest(s.get("final_diff", "")),
    }


def v2_rows(raw: Path) -> list[dict]:
    rows = []
    for folder, target_set in SETS.items():
        for path in sorted((raw / folder).glob("*__*__r*.json")):
            name, label, repeat = path.stem.rsplit("__", 2)
            report = load_json(SweepReport, path)
            rows.append(row_for(target_set, report, name, label, int(repeat.removeprefix("r"))))
    return rows


def v1_report(target_set: str, target: str) -> Path | None:
    for folder in v1_folders(target_set):
        path = folder / f"{target}__{V1}.json"
        if not path.exists():
            continue
        if target_set == "aidev":
            report = load_json(SweepReport, path)
            if _scope_kind(report.stats.get("scope") or {}) == "missing":
                continue
        return path
    return None


def v1_rows(targets: set[tuple[str, str]]) -> list[dict]:
    """v1's gatekeeper run on each SWE-bench and AIDev target that v2 ran."""
    with V1_RESULTS.open() as f:
        counted = {
            (r["target_set"], r["target"]): r for r in csv.DictReader(f) if r["method"] == V1
        }
    rows = []
    for target_set, target in sorted(targets):
        if target_set == "answer keys":
            continue
        path = v1_report(target_set, target)
        main = counted.get((target_set, target))
        if path is None or main is None:
            raise SystemExit(f"no v1 gatekeeper report for {target_set} {target}")
        report = load_json(SweepReport, path)
        row = row_for(target_set, report, target, V1, 0)
        if str(row["lines_removed"]) != main["lines_removed"]:
            raise SystemExit(f"{path} does not match main_results.csv (lines removed)")
        no_outcome = "1" in (main.get("hidden_flaky"), main.get("overload_suspect"))
        row["hidden_changed"] = (
            "" if no_outcome or main["hidden_changed"] == "" else int(main["hidden_changed"])
        )
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", default=str(ROOT / "results" / "raw" / "v2_eval"))
    args = parser.parse_args(argv)
    rows = v2_rows(Path(args.raw))
    rows += v1_rows({(r["target_set"], r["target"]) for r in rows})
    rows = mark_flaky(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["target_set", *FIELDS, "hidden_flaky"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} runs; {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
