"""The blinded diff audit on the v3 runs: v2's audit unchanged (VOYAGER_MODEL_ALT, 3 votes at
temperature 0.3, the majority, the written rubric, never told the method), on the kept code edits
of the INJECT and REAL runs.

    python scripts/experiments/v3/exp_diff_audit_v3.py run [--raw DIR ...]
    python scripts/experiments/v3/exp_diff_audit_v3.py auto [--raw DIR ...]
    python scripts/experiments/v3/exp_diff_audit_v3.py pending [--raw DIR ...]
    python scripts/experiments/v3/exp_diff_audit_v3.py show EDIT [EDIT ...] [--raw DIR ...]
    python scripts/experiments/v3/exp_diff_audit_v3.py record --input checks.jsonl

Collects the runs under results/raw/inject_v3/ ("injected v3") and results/raw/real_v3/
("real v3") of each --raw folder (default: this checkout's results/raw; while the runs go, the
run clones' results/raw), reads each project at the commit its run started from (the injected
clone at the plants commit, the held-out clone at the visible commit), and writes
results/raw/diff_audit_v3/audit.json and results/summary/v3/diff_audit_checks.csv. v2's audit
files are never touched. `auto` applies the injection key's rule (removing planted slop is fine,
removing a trap is wrong) to every kept edit on INJECT, flagged or not.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "results" / "raw" / "diff_audit_v3"
SUMMARY = ROOT / "results" / "summary" / "v3"


def load_v2(raws: list[Path]):
    """v2's audit, pointed at the v3 runs and the v3 output folders."""
    path = HERE.parent / "v2" / "exp_diff_audit.py"
    spec = importlib.util.spec_from_file_location("exp_diff_audit_v3_base", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.OUT, module.SUMMARY = OUT, SUMMARY
    module.CHECKS = SUMMARY / "diff_audit_checks.csv"
    module.CACHE = OUT / "llm_cache.sqlite"
    v2_tree = module.tree_for
    module.runs = lambda: runs_in(raws)
    module.tree_for = lambda repo_id, source: tree_for(module, v2_tree, repo_id, source)
    return module


def runs_in(raws: list[Path]) -> list[tuple[str, str, str, Path]]:
    """(source, method, run, report path) for every finished v3 run under the raw folders; a run
    stopped at its cap has no report and nothing to audit."""
    out = []
    for raw in raws:
        for path in sorted((raw / "inject_v3").glob("*-s*/*.json")):
            if path.name != "key.json" and "results" in json.loads(path.read_text()):
                out.append(("injected v3", path.stem, path.parent.name, path))
        for path in sorted((raw / "real_v3").glob("*/*-r*/report.json")):
            method, _, k = path.parent.name.rpartition("-r")
            out.append(("real v3", method, f"{path.parent.parent.name}/r{k}", path))
    return out


def tree_for(v2, v2_tree, repo_id: str, source: Path):
    """The injected clone at its plants commit, the held-out clone at its visible commit; v2's
    rule for anything else."""
    if repo_id.startswith("aidev:"):
        full, _, sha = repo_id.removeprefix("aidev:").partition("@")
        name = full.replace("/", "__")
        clones = ROOT / "data" / "raw" / "aidev"
        if source.parent.parent.name == "inject_v3":
            return v2.Tree(clones / "injected" / name, sha)
        if source.parent.parent.parent.name == "real_v3":
            return v2.Tree(clones / "heldout" / name, sha)
    return v2_tree(repo_id, source)


def auto(v2) -> int:
    """The injection key's rule on every kept INJECT edit without a check, whatever the auditor
    voted; returns how many checks were added."""
    audit = json.loads((v2.OUT / "audit.json").read_text())
    known = v2.checks()
    rows, plants = [], {}
    for edit_id, record in sorted(audit.items()):
        report = Path(record["report"])
        if edit_id in known or report.parent.parent.name != "inject_v3":
            continue
        if report.parent not in plants:
            key = json.loads((report.parent / "key.json").read_text())
            plants[report.parent] = v2.plant_lines(key)
        verdict = v2.plant_rule(record["diff"], *plants[report.parent])
        if verdict:
            rows.append(
                {
                    "edit": edit_id,
                    "verdict": verdict,
                    "evidence": v2.EVIDENCE[verdict],
                    "checked_by": "rule: injection key",
                    "kind": v2.trap_kind(record["diff"]) if verdict == "wrong" else "",
                }
            )
    v2.write_checks([*known.values(), *rows])
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["run", "auto", "pending", "show", "record"])
    parser.add_argument("edits", nargs="*", help="show: the edits to print")
    parser.add_argument("--raw", type=Path, action="append", help="a results/raw folder")
    parser.add_argument("--input", type=Path, help="record: a JSON lines file (default: stdin)")
    args = parser.parse_args(argv)
    v2 = load_v2(args.raw or [ROOT / "results" / "raw"])
    if args.what == "run":
        print(v2.run_audit())
    elif args.what == "auto":
        print(f"{auto(v2)} checks added by the injection key")
    elif args.what == "pending":
        for row in v2.pending():
            print(json.dumps(row))
    elif args.what == "show":
        print(v2.show(args.edits))
    else:
        lines = (args.input.read_text() if args.input else sys.stdin.read()).splitlines()
        rows = v2.record(v2.checks(), lines)
        v2.write_checks(rows)
        print(f"{len(rows)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
