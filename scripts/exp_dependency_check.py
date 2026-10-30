"""Re-check the dependency removals the AIDev sweeps applied, with the Guard's new check (#2).

    python scripts/exp_dependency_check.py

The sweeps removed declared dependencies with the tests as their only check, and removing a line
from pyproject.toml doesn't uninstall anything. For each repository, this opens the AIDev
workspace (Docker, no LLM), applies advisory's final diff (it holds every removal any method
applied), runs the tests, then makes the removed packages unavailable (Workspace.hide_packages:
a package another installed one requires stays, since the edited requirements would still
install it) and runs the tests again. When they fail, each hidden package is tried alone.

Writes results/summary/aidev_dependency_check.csv: one row per removed package, with its state
(hidden, not installed, or required by another package), whether the removal is verified, and
which methods applied it. The packages that require it are printed, not written: they are names
from the repositories' environments.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exp_aidev_summary import load  # noqa: E402

from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.sandbox import open_workspace  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = [
    ROOT.parent / "cleansweep-runs-3" / "results" / "raw" / "aidev_sweeps",
    ROOT.parent / "cleansweep-runs-5" / "results" / "raw" / "aidev_scoped",
    ROOT.parent / "cleansweep-runs-8" / "results" / "raw" / "aidev_window",
]
METHODS = ["cleansweep-gatekeeper", "cleansweep-advisory", "guard_tests_only"]
OUT = ROOT / "results" / "summary" / "aidev_dependency_check.csv"
FIELDS = ["repo", "package", "state", "verified", "new_failures", "methods"]


def removals(reports: list[dict]) -> dict[str, dict[str, set[str]]]:
    """repo -> package -> the methods whose sweep applied its removal."""
    out: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for rep in reports:
        if rep["_method"] not in METHODS:
            continue
        items = {i["item_id"]: i for i in rep["plan"]["items"]}
        for r in rep["results"]:
            item = items.get(r["item_id"], {})
            if item.get("action") == "remove_dependency" and r["status"] in ("kept", "repaired"):
                out[rep["_repo"]][item["unit"]["name"]].add(rep["_method"])
    return out


def failures(ws, baseline) -> list[str]:
    result = ws.run_tests(None)
    new = [t for t in result.failed_ids if t not in set(baseline.failed_ids)]
    return new or (["errors"] if result.errors > baseline.errors else [])


def check_repo(repo: str, packages: list[str], diff: str, sha: str, cfg: dict) -> dict:
    """package -> (state, new failures without it)."""
    ws = open_workspace(f"aidev:{repo}@{sha}", cfg["core"].get("sandbox"))
    try:
        if not ws.apply_patch(diff):
            raise RuntimeError(f"{repo}: advisory's final diff does not apply")
        baseline = ws.run_tests(None)
        states = ws.hide_packages(packages)
        hidden = [p for p, s in states.items() if s == "hidden"]
        found = {p: [] for p in packages}
        if hidden:
            new = failures(ws, baseline)
            ws.restore_packages()
            if new and len(hidden) == 1:
                found[hidden[0]] = new
            elif new:
                for p in hidden:
                    ws.hide_packages([p])
                    found[p] = failures(ws, baseline)
                    ws.restore_packages()
        return {p: (states[p], found[p]) for p in packages}
    finally:
        ws.close()


def csv_state(state: str) -> str:
    """The state for the CSV: "required by <names>" becomes "required by another package"."""
    return "required by another package" if state.startswith("required by") else state


def main() -> int:
    reports, _ = load([f for f in FOLDERS if f.exists()], [])
    advisory = {r["_repo"]: r for r in reports if r["_method"] == "cleansweep-advisory"}
    cfg = load_config()
    rows = []
    for repo, packages in sorted(removals(reports).items()):
        rep = advisory[repo]
        sha = rep["repo_id"].rsplit("@", 1)[1]
        checked = check_repo(repo, sorted(packages), rep["stats"]["final_diff"], sha, cfg)
        for package, (state, new) in checked.items():
            rows.append(
                {
                    "repo": repo,
                    "package": package,
                    "state": csv_state(state),
                    "verified": int(not new),
                    "new_failures": "; ".join(new[:5]),
                    "methods": "; ".join(sorted(packages[package])),
                }
            )
            print(f"{repo} {package}: {state}, verified {not new}", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    for method in METHODS:
        mine = [r for r in rows if method in r["methods"]]
        print(f"{method}: {sum(r['verified'] for r in mine)} of {len(mine)} removals verified")
    print(OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
