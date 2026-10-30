"""Framework callbacks among shotgun's safe items: what the judge and the Guard did with them.

    python scripts/exp_framework_callbacks.py

A framework callback is a method the framework calls by its name, so no caller appears in the
project: on_*, action_*, watch_*, compute_*, validate_*, handle_*, compose or render, in a class
with a third-party base class somewhere in its ancestry. Methods without such a name that are
registered with a decorator (Textual's @on) are counted apart.

The items are the ones the detectors marked safe (guard_tests_only's plan, where the judge is
advisory). Per CleanSweep method: the callbacks among them, those the judge vetoed (gatekeeper:
safe in guard_tests_only but not in its own plan), and those the Guard kept or rolled back.

Test runs are rebuilt from each plan with the sweep's own batching (make_batches, size 8) and
bisection, letting each item's final status decide whether a check fails; the rebuilt number of
checks is printed next to the report's. A failed check that ran the tests counts toward the
callbacks when a callback is among its rolled-back items. Hours = those test runs x the run's
median test time. Flaky failures and edits that only apply after another one add checks the
rebuild can't see, so its failed test runs are a lower bound. No sweep, no LLM, no Docker.

Writes results/summary/framework_callbacks.csv (one row per method).
"""

from __future__ import annotations

import ast
import csv
import json
import statistics
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace

from cleansweep.core.config import load_config
from cleansweep.scheduler.batching import apply_with_bisection, make_batches

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT.parent / "cleansweep-runs-5" / "results" / "raw" / "aidev_scoped"
TARGET = "shotgun-sh__shotgun"
PROJECT = "shotgun"
METHODS = ["cleansweep-gatekeeper", "cleansweep-advisory", "guard_tests_only"]
PREFIXES = ("on_", "action_", "watch_", "compute_", "validate_", "handle_")
NAMES = {"compose", "render"}
OUT = ROOT / "results" / "summary" / "framework_callbacks.csv"
FIELDS = [
    "method",
    "safe_items",
    "callbacks",
    "decorated",
    "judge_vetoed",
    "to_guard",
    "kept",
    "rolled_back",
    "median_test_min",
    "failed_test_runs",
    "failed_hours",
    "callback_test_runs",
    "callback_hours",
    "run_hours",
    "checks_rebuilt",
    "checks_reported",
]


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Subscript):
        return _name(node.value)
    if isinstance(node, ast.Call):
        return _name(node.func)
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    return node.id if isinstance(node, ast.Name) else ""


def _imports(mod: ast.Module) -> dict[str, str]:
    """Imported name -> its module; relative imports map to the project."""
    out = {}
    for node in ast.walk(mod):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[(a.asname or a.name).split(".")[0]] = a.name
        elif isinstance(node, ast.ImportFrom):
            module = PROJECT if node.level else node.module or ""
            for a in node.names:
                out[a.asname or a.name] = module
    return out


def class_index(tree: Path) -> tuple[dict, dict]:
    """(class name -> [(base names, module imports)], (path, class, method) -> FunctionDef)."""
    classes: dict[str, list] = {}
    methods = {}
    for path in tree.rglob("*.py"):
        try:
            mod = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        imps = _imports(mod)
        rel = path.relative_to(tree).as_posix()
        for node in ast.walk(mod):
            if isinstance(node, ast.ClassDef):
                classes.setdefault(node.name, []).append(([_name(b) for b in node.bases], imps))
                for f in node.body:
                    if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef):
                        methods[(rel, node.name, f.name)] = f
    return classes, methods


def framework_of(name: str, classes: dict, seen: set[str] | None = None) -> str | None:
    """The third-party package a class inherits from, through the project's own classes."""
    seen = seen if seen is not None else {name}
    for bases, imps in classes.get(name, []):
        for base in bases:
            top = imps.get(base.split(".")[0], "").split(".")[0]
            if top and top != PROJECT and top not in sys.stdlib_module_names:
                return top
            last = base.split(".")[-1]
            if last and last not in seen:
                seen.add(last)
                found = framework_of(last, classes, seen)
                if found:
                    return found
    return None


def kind(item: dict, classes: dict, methods: dict) -> str:
    """'callback', 'decorated' or '' for a plan item."""
    parts = (item["unit"]["name"] or "").split(".")
    if item["unit"]["kind"] != "function" or len(parts) < 2:
        return ""
    cls, meth = parts[-2], parts[-1]
    if not framework_of(cls, classes):
        return ""
    if meth in NAMES or meth.startswith(PREFIXES):
        return "callback"
    node = methods.get((item["unit"]["path"], cls, meth))
    decorators = [_name(d).split(".")[-1] for d in node.decorator_list] if node else []
    return "decorated" if "on" in decorators else ""


def rebuilt_checks(rep: dict) -> tuple[list[tuple[list[str], bool]], int]:
    """([(rolled-back item ids, ran the tests)] per failed check, number of checks)."""
    status = {r["item_id"]: r for r in rep["results"]}
    safe = [
        SimpleNamespace(**{k: i[k] for k in ("item_id", "category", "safe_score", "evidence")})
        for i in rep["plan"]["items"]
        if i["lane"] == "safe" and i["action"] != "report_only"
    ]
    failed = []

    def check(batch) -> bool:
        applied = [i.item_id for i in batch if status[i.item_id]["status"] != "skipped"]
        bad = [k for k in applied if status[k]["status"] == "rolled_back"]
        if bad:
            # a batch that broke compilation fails before the tests run
            ran = not any(status[k]["notes"].startswith("compile") for k in bad)
            failed.append((bad, ran))
        return not bad

    n = apply_with_bisection(make_batches(safe, 8), check)["n_checks"]
    return failed, n


def export_tree(clone: Path, sha: str, dest: Path) -> Path:
    tar = dest / "tree.tar"
    tar.write_bytes(
        subprocess.run(
            ["git", "archive", "--format=tar", sha], cwd=clone, capture_output=True, check=True
        ).stdout
    )
    with tarfile.open(tar) as f:
        f.extractall(dest / "tree", filter="data")
    return dest / "tree"


def method_row(method: str, rep: dict, safe_ids: set[str], kinds: dict[str, str]) -> dict:
    status = {r["item_id"]: r["status"] for r in rep["results"]}
    own_safe = {
        i["item_id"]
        for i in rep["plan"]["items"]
        if i["lane"] == "safe" and i["action"] != "report_only"
    }
    calls = {k for k in safe_ids if kinds.get(k) == "callback"}
    failed, n = rebuilt_checks(rep)
    runs = [bad for bad, ran in failed if ran]
    on_calls = sum(any(k in calls for k in bad) for bad in runs)
    durations = [
        r["tests"]["duration_s"] for r in rep["results"] if isinstance(r.get("tests"), dict)
    ]
    median = statistics.median(durations) if durations else 0.0
    return {
        "method": method,
        "safe_items": len(safe_ids),
        "callbacks": len(calls),
        "decorated": sum(kinds.get(k) == "decorated" for k in safe_ids),
        "judge_vetoed": len(calls - own_safe),
        "to_guard": len(calls & own_safe),
        "kept": sum(status.get(k) in ("kept", "repaired") for k in calls),
        "rolled_back": sum(status.get(k) == "rolled_back" for k in calls),
        "median_test_min": round(median / 60, 1),
        "failed_test_runs": len(runs),
        "failed_hours": round(len(runs) * median / 3600, 1),
        "callback_test_runs": on_calls,
        "callback_hours": round(on_calls * median / 3600, 1),
        "run_hours": round(rep["stats"]["wall_seconds"] / 3600, 1),
        "checks_rebuilt": n,
        "checks_reported": rep["stats"].get("n_checks"),
    }


def main() -> int:
    reports = {
        m: json.loads((REPORTS / f"{TARGET}__{m}.json").read_text())
        for m in METHODS
        if (REPORTS / f"{TARGET}__{m}.json").exists()
    }
    base = reports["guard_tests_only"]
    sha = base["repo_id"].split("@")[1]
    clone = ROOT / load_config()["data"]["aidev"]["clones"] / TARGET
    with tempfile.TemporaryDirectory() as tmp:
        classes, methods = class_index(export_tree(clone, sha, Path(tmp)))
    items = {i["item_id"]: i for i in base["plan"]["items"]}
    safe_ids = {k for k, i in items.items() if i["lane"] == "safe" and i["action"] != "report_only"}
    kinds = {k: kind(items[k], classes, methods) for k in safe_ids}
    frameworks = {
        framework_of(items[k]["unit"]["name"].split(".")[-2], classes) for k in safe_ids if kinds[k]
    }
    print(f"frameworks: {', '.join(sorted(f for f in frameworks if f))}")
    for k in sorted(safe_ids, key=lambda k: items[k]["unit"]["name"] or ""):
        if kinds[k]:
            print(f"  {kinds[k]:9} {items[k]['unit']['path']}::{items[k]['unit']['name']}")
    rows = []
    for method in METHODS:
        if method not in reports:
            print(f"{method}: no report yet")
            continue
        rows.append(method_row(method, reports[method], safe_ids, kinds))
        print(rows[-1])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
