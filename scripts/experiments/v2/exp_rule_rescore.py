"""The extended framework-callback rule measured on the finished injected runs: the kept edits it
would have moved to the suggest lane, and each run's numbers without them ("with rule") next to
the numbers as run, which stay the reported ones.

    python scripts/experiments/v2/exp_rule_rescore.py moved
    python scripts/experiments/v2/exp_rule_rescore.py run
    python scripts/experiments/v2/exp_rule_rescore.py table

moved: per run, the kept edits the rule would have moved (no Docker). The rule looks at the kept
dead-code and duplicate edits on methods, with the code graph of the run's starting commit, for
the methods that plan with build_plan (v1, the team and its ablations, the single agent; not the
one-shot baseline).
run: for a run where the rule moves any edit, the run's other kept edits are applied in order to
the starting commit, the plants are scored, and the hidden test runs before and after that diff
in a fresh workspace, as exp_inject.py does; a run where it moves none keeps its numbers.
Writes results/raw/inject_rule/<project>-s<seed>/<method>.json.
table: results/summary/v2/inject_rule.csv: per method, as run and with the rule: kept edits the
rule moves, planted slop removed, traps removed, hidden tests changed, and the diff audit's wrong
edits (all tiers, and confirmed) carried over from diff_audit_checks.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import exp_inject as inject  # noqa: E402
from exp_diff_audit import checks, edit_key, kept_edits, tier  # noqa: E402

from cleansweep.analysis import build_graph  # noqa: E402
from cleansweep.data.swebench import data_path  # noqa: E402
from cleansweep.sandbox.cleanup import on_start  # noqa: E402

OUT = inject.RAW.parent / "inject_rule"
TABLE = inject.SUMMARY / "inject_rule.csv"
UNPLANNED = {"one_shot_llm"}  # no build_plan, so no rule


def runs() -> list[tuple[Path, Path]]:
    """(project folder, report) for every finished injected run of a planned method."""
    out = []
    for folder in sorted(inject.RAW.glob("*-s*")):
        for report in sorted(folder.glob("*.json")):
            if report.name != "key.json" and report.stem not in UNPLANNED:
                out.append((folder, report))
    return out


def start(folder: Path, key: dict) -> tuple[Path, str]:
    """(the injected tree, the commit the runs started from)."""
    name = folder.name.rsplit("-s", 1)[0]
    if name == "toy":
        tree = folder / "repo"
        return tree, key.get("sha") or inject._git(tree, "rev-parse", "HEAD")
    return data_path(inject.CLONES) / name, key.get("sha") or key["target"].partition("@")[2]


def export(tree: Path, sha: str) -> Path:
    """A git repository holding the tree at sha, in a temporary folder."""
    dest, _ = inject.final_tree(tree, "", sha)
    return dest


def moved(report: dict, graph) -> list[dict]:
    """The kept dead-code and duplicate edits on a method a framework calls by name."""
    items = {i["item_id"]: i for i in report["plan"]["items"]}
    out = []
    for edit in kept_edits(report):
        item = items.get(edit["item_id"], {})
        unit = item.get("unit") or {}
        if item.get("category") not in ("dead_code", "duplicate") or not unit.get("name"):
            continue
        framework = graph.framework_callback(f"{unit['path']}::{unit['name']}")
        if framework:
            out.append({**edit, "name": unit["name"], "framework": framework})
    return out


def as_run(report: dict) -> dict:
    plants = report["stats"]["inject"]["plants"]
    return {
        "slop_removed": sum(p["removed"] for p in plants if p["kind"] == "slop"),
        "traps_removed": sum(p["removed"] for p in plants if p["kind"] == "trap"),
        "hidden_changed": report["stats"]["hidden"].get("behavior_changed"),
    }


def without(tree: Path, sha: str, report: dict, skip: set[str]) -> tuple[Path, str, int]:
    """(the tree with the run's kept edits but the skipped ones, its diff, edits that no longer
    apply)."""
    work = export(tree, sha)
    failed = 0
    for result in report["results"]:
        if result["status"] != "kept" or not result.get("diff") or result["item_id"] in skip:
            continue
        diff = result["diff"] if result["diff"].endswith("\n") else result["diff"] + "\n"
        proc = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=work,
            input=diff,
            text=True,
            capture_output=True,
        )
        failed += proc.returncode != 0
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    diff = subprocess.run(
        ["git", "diff", "--cached", "--binary", "HEAD"],
        cwd=work,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return work, diff, failed


def rescore(folder: Path, report_path: Path, cfg: dict, docker: bool) -> dict:
    key = json.loads((folder / "key.json").read_text())
    report = json.loads(report_path.read_text())
    tree, sha = start(folder, key)
    base = export(tree, sha)
    try:
        found = moved(report, build_graph(str(base)))
    finally:
        shutil.rmtree(base.parent, ignore_errors=True)
    out = {"method": report_path.stem, "run": folder.name, "as_run": as_run(report)}
    out["moved"] = [{k: m[k] for k in ("item_id", "path", "name", "framework")} for m in found]
    if not found or not docker:
        out["with_rule"] = out["as_run"] if not found else None
        return out
    work, diff, failed = without(tree, sha, report, {m["item_id"] for m in found})
    try:
        plants = inject.score(work, key)
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)
    hidden = inject.hidden_check(key["target"], diff, folder / "hidden", cfg)
    out["not_applied"] = failed
    out["with_rule"] = {
        "slop_removed": sum(p["removed"] for p in plants if p["kind"] == "slop"),
        "traps_removed": sum(p["removed"] for p in plants if p["kind"] == "trap"),
        "hidden_changed": hidden.get("behavior_changed"),
    }
    return out


def run(docker: bool = True) -> list[dict]:
    cfg = inject.load_config(
        {"reviewer": {"scope": "repo"}, "core": {"sandbox": {"aidev_clones": inject.CLONES}}}
    )
    out = []
    for folder, report in runs():
        path = OUT / folder.name / report.name
        if docker and path.exists():
            out.append(json.loads(path.read_text()))
            continue
        row = rescore(folder, report, cfg, docker)
        out.append(row)
        if docker:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(row, indent=1))
        if row["moved"]:
            print(json.dumps({k: row[k] for k in ("run", "method", "moved")}), flush=True)
    return out


def table() -> Path:
    known = checks()
    rows: dict[str, dict] = {}
    for path in sorted(OUT.glob("*-s*/*.json")):
        rec = json.loads(path.read_text())
        report = json.loads((inject.RAW / rec["run"] / path.name).read_text())
        gone = {m["item_id"] for m in rec["moved"]}
        row = rows.setdefault(rec["method"], {"method": rec["method"], "runs": 0, "moved": 0})
        row["runs"] += 1
        row["moved"] += len(gone)
        for when, numbers in (("as_run", rec["as_run"]), ("with_rule", rec["with_rule"])):
            for field, value in numbers.items():
                row[f"{field}_{when}"] = row.get(f"{field}_{when}", 0) + int(value or 0)
        for edit in kept_edits(report):
            check = known.get(edit_key(report["repo_id"], edit["path"], edit["diff"]), {})
            if check.get("verdict") != "wrong":
                continue
            confirmed = tier(check) == "confirmed"
            for when in ("as_run", "with_rule"):
                if when == "with_rule" and edit["item_id"] in gone:
                    continue
                row[f"wrong_{when}"] = row.get(f"wrong_{when}", 0) + 1
                row[f"wrong_confirmed_{when}"] = row.get(f"wrong_confirmed_{when}", 0) + confirmed
    fields = ["method", "runs", "moved"]
    for name in ("slop_removed", "traps_removed", "hidden_changed", "wrong", "wrong_confirmed"):
        fields += [f"{name}_as_run", f"{name}_with_rule"]
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    with TABLE.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, restval=0)
        writer.writeheader()
        writer.writerows(rows[m] for m in sorted(rows))
    return TABLE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["moved", "run", "table"])
    args = parser.parse_args(argv)
    if args.what == "table":
        print(table())
    else:
        on_start()
        rows = run(docker=args.what == "run")
        print(
            f"{sum(bool(r['moved']) for r in rows)} of {len(rows)} runs have edits the rule moves"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
