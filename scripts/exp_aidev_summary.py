"""AIDev sweeps: what each method found, applied and rolled back, and the hidden-test coverage.

    python scripts/exp_aidev_summary.py [--runs ../cleansweep-runs-3/results/raw/aidev_sweeps]
        [--tests ../cleansweep-runs-3/.cleansweep/hidden_tests]

Reads the AIDev sweep reports (exp_swebench.py on data/splits/aidev_repos.json). Writes
results/summary/aidev_sweeps.csv (one row per method and category) and aidev_sweeps.md:
items proposed and applied by category (are there code-level items, not just files?),
rollbacks by the check that caused them (tests, probes, compile), per repository the
second-model hidden tests, and the cause of each hidden change: a changed hidden test that
imports or calls a function or class the cleanup deleted, or tests a file it deleted, counts as
"deleted code", any other as "behavior". Hidden-change rates with CIs per method are in
main_table.md (exp_collect.py, exp_tables.py).
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
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
CHECKS = ("compile", "tests", "ast", "probes")
DEF = re.compile(r"^([-+])[ \t]*(?:async[ \t]+)?(?:def|class)[ \t]+(\w+)", re.MULTILINE)
DELETED_FILE = re.compile(r"^--- a/(.+)\n\+\+\+ /dev/null", re.MULTILINE)


def _applied(result: dict) -> bool:
    return result["status"] in ("kept", "repaired") and bool((result.get("diff") or "").strip())


def rollback_check(result: dict) -> str:
    """Which Guard check rolled an item back ("<check> failed: ..." in its notes)."""
    note = result.get("notes") or ""
    return next((c for c in CHECKS if note.startswith(f"{c} failed")), "other")


def removed_names(diff: str) -> set[str]:
    """Functions and classes whose definition the diff deletes and does not add back."""
    found: dict[str, set[str]] = {"-": set(), "+": set()}
    for sign, name in DEF.findall(diff):
        found[sign].add(name)
    return found["-"] - found["+"]


def _names(node: ast.AST) -> set[str]:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            out |= {a.name.split(".")[-1] for a in n.names}
    return out


def uses_deleted(test_id: str, removed: set[str], tests_dir: Path, files: set[str]) -> bool:
    """Does the hidden test (or its file's imports) use a name the cleanup deleted, or test a
    source file in `files` (the files it deleted)?"""
    module, _, func = test_id.partition("::")
    parts = module.split(".")
    path = tests_dir / f"{parts[1]}.py" if len(parts) > 1 else None
    if path is None or not path.exists():
        return False
    meta = tests_dir / "meta.json"
    sources = json.loads(meta.read_text())["sources"] if meta.exists() else {}
    if sources.get(path.name) in files:
        return True
    tree = ast.parse(path.read_text(encoding="utf-8"))
    used = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            used |= _names(node)
    func = func.split("[")[0]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
            used |= _names(node)
    return bool(used & removed)


def hidden_cause(rep: dict) -> str:
    """Cause of a hidden change: "deleted code" when every changed hidden test uses a name or
    tests a file the cleanup deleted, "behavior" otherwise; "" without a hidden change."""
    hidden = rep["stats"].get("hidden") or {}
    changed = hidden.get("alt_changed") or []
    if not hidden.get("behavior_changed") or not changed:
        return ""
    diff = rep["stats"].get("final_diff", "")
    removed, files = removed_names(diff), set(DELETED_FILE.findall(diff))
    tests_dir = rep.get("_tests") or Path("missing")
    if all(uses_deleted(t, removed, tests_dir, files) for t in changed):
        return "deleted code"
    return "behavior"


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
        if hidden.get("available") and hidden.get("behavior_changed") is not None:
            totals["hidden_checked"] += 1
            totals["hidden_changed"] += bool(hidden.get("behavior_changed"))
            cause = hidden_cause(rep)
            if cause:
                totals[f"hidden_{cause.split()[0]}"] += 1
        for item in rep["plan"]["items"]:
            c = by_cat.setdefault((method, item["category"]), Counter())
            c["proposed"] += 1
            c[f"lane_{item['lane']}"] += 1
            result = status.get(item["item_id"], {})
            if _applied(result):
                c["applied"] += 1
                level = "files" if item.get("action") == "delete_file" else "code"
                totals[f"applied_{level}"] += 1
            elif "could not be applied" in (result.get("notes") or ""):
                c["not_applicable"] += 1
                totals["could_not_apply"] += 1
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
            "could_not_apply": c["not_applicable"],
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


def change_rows(reports: list[dict]) -> list[dict]:
    """One row per run whose hidden checks changed: how many tests, the cause, and the deleted
    names and files that the changed tests use."""
    rows = []
    for rep in reports:
        hidden = rep["stats"].get("hidden") or {}
        cause = hidden_cause(rep)
        if not cause:
            continue
        diff = rep["stats"].get("final_diff", "")
        tests_dir = rep.get("_tests") or Path("missing")
        changed = hidden["alt_changed"]
        used = sorted(
            name
            for name in removed_names(diff)
            if any(uses_deleted(t, {name}, tests_dir, set()) for t in changed)
        ) + sorted(
            Path(f).name
            for f in DELETED_FILE.findall(diff)
            if any(uses_deleted(t, set(), tests_dir, {f}) for t in changed)
        )
        rows.append(
            {
                "repo": rep["_repo"],
                "method": rep["_method"],
                "changed_tests": len(hidden["alt_changed"]),
                "cause": cause,
                "deleted_code_used": ", ".join(used[:4]) + (" ..." if len(used) > 4 else ""),
            }
        )
    return sorted(rows, key=lambda r: (r["repo"], METHODS.index(r["method"])))


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


def load(folder: Path, tests_root: Path) -> list[dict]:
    reports = []
    for path in sorted(folder.glob("*__*__*.json")):
        owner, name, method = path.stem.rsplit("__", 2)
        data = json.loads(path.read_text())
        tests = next(iter(sorted(tests_root.glob(f"aidev_{owner}_{name}@*"))), None)
        reports.append({**data, "_repo": f"{owner}/{name}", "_method": method, "_tests": tests})
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
    parser.add_argument(
        "--tests", default=str(ROOT.parent / "cleansweep-runs-3" / ".cleansweep" / "hidden_tests")
    )
    args = parser.parse_args(argv)
    reports = load(Path(args.runs), Path(args.tests))
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
        "could_not_apply",
        "hidden_checked",
        "hidden_changed",
        "hidden_deleted",
        "hidden_behavior",
        "llm_retries",
        "llm_failures",
    ]
    md = [
        "# AIDev sweeps",
        "",
        f"{len(reports)} reports on {repos} of the 20 runnable repos used (1 excluded), at their "
        "head sha. Agent scope: lines and files that agent pull requests wrote (first-parent "
        "blame). Applied files = deleted files; applied code = every other applied edit. "
        "Could not apply = the edit tool could not make the change (e.g. a dependency listed "
        "in pyproject.toml). Hidden checked = runs whose diff applied in a workspace with "
        "second-model tests; hidden_deleted = changes where every changed test uses a function, "
        "class or file the cleanup deleted; hidden_behavior = any other change.",
        "",
        *_table(method_rows, method_cols),
        "",
        "## Items by category",
        "",
        *_table(
            cat_rows,
            [
                "method",
                "category",
                "proposed",
                "safe_lane",
                "applied",
                "rolled_back",
                "could_not_apply",
            ],
        ),
        "",
        "## Hidden changes",
        "",
        *_table(
            change_rows(reports),
            ["repo", "method", "changed_tests", "cause", "deleted_code_used"],
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
