"""AIDev sweeps: what each method found, applied and rolled back, and the hidden-test coverage.

    python scripts/exp_aidev_summary.py [--runs ../cleansweep-runs-3/results/raw/aidev_sweeps]

Reads the AIDev sweep reports (exp_swebench.py on data/splits/aidev_repos.json). Writes
results/summary/aidev_sweeps.csv (one row per method and category) and aidev_sweeps.md:
items proposed and applied by category (are there code-level items, not just files?),
rollbacks by the check that caused them (tests, probes, compile), and per repository the
second-model hidden tests. Hidden-change rates with CIs per method are in main_table.md
(exp_collect.py, exp_tables.py).
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "summary" / "aidev_sweeps"
METHODS = [
    "cleansweep-gatekeeper",
    "cleansweep-advisory",
    "guard_tests_only",
    "tools_only",
    "one_shot_llm",
]
FILE_LEVEL = {"leftover_file"}
CHECKS = ("compile", "tests", "ast", "probes")


def _applied(result: dict) -> bool:
    return result["status"] in ("kept", "repaired") and bool((result.get("diff") or "").strip())


def rollback_check(result: dict) -> str:
    """Which Guard check rolled an item back ("<check> failed: ..." in its notes)."""
    note = result.get("notes") or ""
    return next((c for c in CHECKS if note.startswith(f"{c} failed")), "other")


def summarize(reports: list[dict]) -> tuple[list[dict], list[dict]]:
    """(rows per method and category, rows per method)."""
    by_cat: dict[tuple[str, str], Counter] = {}
    by_method: dict[str, Counter] = {}
    for rep in reports:
        method = rep["_method"]
        status = {r["item_id"]: r for r in rep["results"]}
        totals = by_method.setdefault(method, Counter())
        totals["repos"] += 1
        totals["lines_removed"] += rep["stats"].get("lines_removed", 0)
        totals["files_removed"] += rep["stats"].get("files_removed", 0)
        totals["llm_retries"] += rep["stats"].get("llm_retries", 0)
        totals["llm_failures"] += rep["stats"].get("llm_failures", 0)
        hidden = rep["stats"].get("hidden") or {}
        if hidden.get("available"):
            totals["hidden_checked"] += 1
            totals["hidden_changed"] += bool(hidden.get("behavior_changed"))
        for item in rep["plan"]["items"]:
            c = by_cat.setdefault((method, item["category"]), Counter())
            c["proposed"] += 1
            c[f"lane_{item['lane']}"] += 1
            result = status.get(item["item_id"], {})
            if _applied(result):
                c["applied"] += 1
                level = "files" if item["category"] in FILE_LEVEL else "code"
                totals[f"applied_{level}"] += 1
            elif result.get("status") == "rolled_back":
                c["rolled_back"] += 1
                totals[f"rolled_back_{rollback_check(result)}"] += 1
    cat_rows = [
        {
            "method": m,
            "category": cat,
            "proposed": c["proposed"],
            "safe_lane": c["lane_safe"],
            "applied": c["applied"],
            "rolled_back": c["rolled_back"],
        }
        for (m, cat), c in sorted(
            by_cat.items(), key=lambda kv: (METHODS.index(kv[0][0]), kv[0][1])
        )
    ]
    method_rows = [
        {"method": m, **{k: by_method[m][k] for k in sorted(by_method[m])}}
        for m in METHODS
        if m in by_method
    ]
    return cat_rows, method_rows


def hidden_rows(reports: list[dict]) -> list[dict]:
    """Second-model hidden tests per repository (the same tests for every method)."""
    out = {}
    for rep in reports:
        hidden = rep["stats"].get("hidden") or {}
        if hidden.get("available") and rep["_repo"] not in out:
            out[rep["_repo"]] = {
                "repo": rep["_repo"],
                "test_files": hidden.get("alt_files", 0),
                "stable_tests": hidden.get("alt_tests", 0),
                "passing": hidden.get("alt_passing", 0),
                "unstable": hidden.get("alt_unstable", 0),
            }
    return sorted(out.values(), key=lambda r: r["repo"])


def load(folder: Path) -> list[dict]:
    reports = []
    for path in sorted(folder.glob("*__*__*.json")):
        owner, name, method = path.stem.rsplit("__", 2)
        data = json.loads(path.read_text())
        reports.append({**data, "_repo": f"{owner}/{name}", "_method": method})
    return reports


def _table(rows: list[dict], cols: list[str]) -> list[str]:
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    return lines + ["| " + " | ".join(str(r.get(c, 0)) for c in cols) + " |" for r in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--runs",
        default=str(ROOT.parent / "cleansweep-runs-3" / "results" / "raw" / "aidev_sweeps"),
    )
    args = parser.parse_args(argv)
    reports = load(Path(args.runs))
    cat_rows, method_rows = summarize(reports)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.with_suffix(".csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(cat_rows[0]) if cat_rows else ["method"])
        writer.writeheader()
        writer.writerows(cat_rows)
    repos = len({r["_repo"] for r in reports})
    method_cols = [
        "method",
        "repos",
        "applied_files",
        "applied_code",
        "files_removed",
        "lines_removed",
        *[f"rolled_back_{c}" for c in CHECKS],
        "hidden_checked",
        "hidden_changed",
        "llm_retries",
        "llm_failures",
    ]
    md = [
        "# AIDev sweeps",
        "",
        f"{len(reports)} reports on {repos} of the 20 runnable repos used (1 excluded), at their "
        "head sha. Agent scope: lines and files that agent pull requests wrote (first-parent "
        "blame). Applied code = applied items that are not whole files.",
        "",
        *_table(method_rows, method_cols),
        "",
        "## Items by category",
        "",
        *_table(
            cat_rows, ["method", "category", "proposed", "safe_lane", "applied", "rolled_back"]
        ),
        "",
        "## Second-model hidden tests (glm-5-3), per repository",
        "",
        *_table(
            hidden_rows(reports), ["repo", "test_files", "stable_tests", "passing", "unstable"]
        ),
    ]
    OUT.with_suffix(".md").write_text("\n".join(md) + "\n")
    print(f"{len(reports)} reports -> {OUT.with_suffix('.md').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
