"""Self-sweep: CleanSweep on its own code, in gatekeeper and then advisory mode.

    python scripts/exp_self_sweep.py [--ref main] [--modes gatekeeper advisory]

The target is a copy of this repository at --ref (git archive). The Reviewer looks at the whole
repository (repo scope) except tests/fixtures/, demo/, results/, data/ and .notes/, and the
Guard's tests are the project's own offline suite (pytest -m "not llm and not docker and not
network and not slow"), run against the copy's own src/. The LLM is used as in any sweep
(judge, repair, probes).

Writes results/raw/self_sweep/<mode>.json (the sweep report) and prints a summary per mode:
items by category and lane, kept, rolled back by check, lines removed, and the judge's vetoes.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

from cleansweep.core.config import load_config
from cleansweep.core.io import save_json
from cleansweep.workflow import run_sweep

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "raw" / "self_sweep"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="main")
    parser.add_argument("--modes", nargs="+", default=["gatekeeper", "advisory"])
    args = parser.parse_args(argv)
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
