"""Self-sweep: CleanSweep on its own code, in gatekeeper and then advisory mode.

    python scripts/experiments/v1/exp_self_sweep.py [--ref main] [--modes gatekeeper advisory]

The target is a copy of this repository at --ref (git archive). The Reviewer looks at the whole
repository (repo scope) except tests/fixtures/, demo/, results/, data/ and .notes/, and the
Guard's tests are the project's own offline suite (pytest -m "not llm and not docker and not
network and not slow"), run against the copy's own src/. The LLM is used as in any sweep
(judge, repair, probes).

Writes results/raw/self_sweep/<mode>.json (the sweep report) and prints a summary per mode:
items by category and lane, kept, rolled back by check, lines removed, and the judge's vetoes.

    python scripts/experiments/v1/exp_self_sweep.py --table [--ref a439dcd]

writes results/summary/self_sweep.csv from the saved reports, one row per mode, plus
format_items_now: the format items today's detector finds on the same copy (format edits follow
the project's ruff settings since the self-sweep found them ignored).
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

from cleansweep.core.config import load_config
from cleansweep.core.io import load_json, save_json
from cleansweep.core.models import SweepReport
from cleansweep.reviewer.detectors import detect_formatting, excluded
from cleansweep.workflow import run_sweep

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "results" / "raw" / "self_sweep"
TABLE = ROOT / "results" / "summary" / "self_sweep.csv"
CATEGORIES = ["format", "dead_code", "duplicate", "security", "other"]
EXCLUDE = ["tests/fixtures/", "demo/", "results/", "data/", ".notes/"]
OFFLINE = '-m "not llm and not docker and not network and not slow"'
VETO = "Judge thinks this is still used"


def copy_at(ref: str, dest: Path) -> Path:
    tar = dest / "repo.tar"
    tar.write_bytes(
        subprocess.run(
            ["git", "archive", "--format=tar", ref], cwd=ROOT, capture_output=True, check=True
        ).stdout
    )
    with tarfile.open(tar) as f:
        f.extractall(dest / "cleansweep", filter="data")
    tar.unlink()
    return dest / "cleansweep"


def summary(report) -> str:
    status = {r.item_id: r for r in report.results}
    lines = [
        f"items {len(report.plan.items)}: "
        + ", ".join(f"{c} {n}" for c, n in Counter(i.category for i in report.plan.items).items()),
        "lanes: "
        + ", ".join(f"{k} {n}" for k, n in Counter(i.lane for i in report.plan.items).items()),
        f"judge vetoes: {sum(i.reason.startswith(VETO) for i in report.plan.items)}",
        "kept: " + str(sum(r.status in ("kept", "repaired") for r in report.results)),
        "rolled back: "
        + ", ".join(
            f"{k} {n}"
            for k, n in Counter(
                r.notes.split(" failed", 1)[0] for r in report.results if r.status == "rolled_back"
            ).items()
        ),
        f"lines removed {report.stats['lines_removed']}, test runs {report.stats['test_runs']}",
    ]
    return "\n  ".join(lines) + f"\n  results: {len(status)}"


def row(mode: str, report) -> dict:
    """One table row: items by category and lane, what the Guard did, and the cost."""
    items = report.plan.items
    checks = Counter(
        r.notes.split(" failed", 1)[0] for r in report.results if r.status == "rolled_back"
    )
    return {
        "mode": mode,
        "items": len(items),
        **{c: sum(i.category == c for i in items) for c in CATEGORIES},
        "safe": sum(i.lane == "safe" for i in items),
        "suggest": sum(i.lane == "suggest" for i in items),
        "judge_vetoes": sum(i.reason.startswith(VETO) for i in items),
        "kept": sum(r.status in ("kept", "repaired") for r in report.results),
        "rolled_back_tests": checks["tests"],
        "rolled_back_probes": checks["probes"],
        "lines_removed": report.stats["lines_removed"],
        "test_runs": report.stats["test_runs"],
        "llm_failures": report.stats.get("llm_failures", 0),
        "minutes": round(report.stats["wall_seconds"] / 60, 1),
    }


def format_items_now(ref: str) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        target = copy_at(ref, Path(tmp))
        return sum(not excluded(i.unit.path, EXCLUDE) for i in detect_formatting(str(target)))


def write_table(modes: list[str], ref: str) -> Path:
    rows = [row(m, load_json(SweepReport, OUT / f"{m}.json")) for m in modes]
    now = format_items_now(ref)
    for r in rows:
        r["format_items_now"] = now
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    with TABLE.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return TABLE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="main")
    parser.add_argument("--modes", nargs="+", default=["gatekeeper", "advisory"])
    parser.add_argument("--table", action="store_true", help="only write the table")
    args = parser.parse_args(argv)
    if args.table:
        print(write_table(args.modes, args.ref).relative_to(ROOT))
        return 0
    # the Guard's pytest runs in the workspace copy: import its src/ and run the offline set
    os.environ["PYTHONPATH"] = "src"
    os.environ["PYTEST_ADDOPTS"] = OFFLINE
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        target = copy_at(args.ref, Path(tmp))
        for mode in args.modes:
            cfg = load_config()
            cfg["reviewer"] = {**cfg["reviewer"], "judge_mode": mode, "exclude": EXCLUDE}
            report = run_sweep(str(target), cfg, method="cleansweep")
            save_json(report, OUT / f"{mode}.json")
            print(f"{mode}:\n  {summary(report)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
