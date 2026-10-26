"""Guard strength: mutation score, PatchDiff recall and false alarms, via guard.verify.

    python scripts/exp_guard_strength.py --local tests/fixtures/toy_repo \\
        .cleansweep/demo/shop_app --tier data/splits/swebench_tier1.json [--tier ...] [--resume]

- Mutation score: mutate functions one at a time (toy/demo: up to 20 package functions per
  target; SWE-bench: up to 5 per patch, among functions the agent patch wrote or changed in
  project code). A mutant is caught if verify(before, mutated) fails; we record which check
  (compile, tests or probes) caught it.
- PatchDiff recall: for patches with differs_from_oracle, verify(agent patch, oracle patch).
- False alarms: verify on two identical copies, probing the touched functions anyway.

One JSON of records per target in results/raw/guard_strength/, and a summary in
results/summary/guard_strength.csv.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from cleansweep.analysis import build_graph
from cleansweep.analysis.graph import is_test_file
from cleansweep.analysis.scope import agent_scope
from cleansweep.core.config import load_config
from cleansweep.core.models import CodeUnit
from cleansweep.eval.mutation import mutants, sample
from cleansweep.guard import verify
from cleansweep.llm import get_client
from cleansweep.sandbox import open_workspace
from cleansweep.sandbox.swebench_docker import drop_files, patch_files

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw" / "guard_strength"
SUMMARY = ROOT / "results" / "summary" / "guard_strength.csv"


def _check(ok: bool, info: dict) -> str | None:
    return None if ok else info.get("check", "other")


def run_mutants(before, after, units, cfg, llm, limit, seed=0) -> list[dict]:
    pool = []
    for unit in units:
        text = (Path(before.path) / unit.path).read_text(encoding="utf-8", errors="replace")
        pool += mutants(text, unit.path, unit.name)
    records = []
    for m in sample(pool, limit, seed):
        t0 = time.time()
        (Path(after.path) / m.path).write_text(m.source, encoding="utf-8")
        touched = [CodeUnit(m.path, "function", m.qualname)]
        ok, info = verify(before, after, touched, llm, cfg)
        after.rollback(after.base)
        records.append(
            {
                "experiment": "mutation",
                "unit": m.key,
                "operator": m.operator,
                "line": m.line,
                "caught": not ok,
                "check": _check(ok, info),
                "probe_cases": getattr(info.get("diff_check"), "n_cases", None),
                "seconds": round(time.time() - t0, 1),
            }
        )
    return records


def false_alarm(before, after, units, cfg, llm) -> dict:
    t0 = time.time()
    ok, info = verify(before, after, units[:10], llm, {**cfg, "probe_touched": True})
    return {
        "experiment": "false_alarm",
        "unit": f"{len(units[:10])} functions",
        "caught": not ok,  # here "caught" means a false alarm
        "check": _check(ok, info),
        "probe_cases": getattr(info.get("diff_check"), "n_cases", None),
        "seconds": round(time.time() - t0, 1),
    }


def package_functions(repo_dir: str, graph) -> list[CodeUnit]:
    """Functions in package modules (not tests, not loose scripts)."""
    out = []
    for u in graph.units():
        folder = (Path(repo_dir) / u.path).parent
        if u.kind == "function" and not is_test_file(u.path) and (folder / "__init__.py").exists():
            out.append(u)
    return sorted(out, key=lambda u: u.key)


def guard_cfg(base: dict, before, graph) -> dict:
    return {**base, "baseline": before.run_tests(None), "graph": graph, "items": []}


def local_target(path: str, cfg: dict, llm, limit: int) -> list[dict]:
    sandbox = cfg["core"]["sandbox"]
    before = open_workspace(path, sandbox)
    after = before.fork()
    same = before.fork()
    try:
        graph = build_graph(before.path)
        gcfg = guard_cfg(cfg["core"]["guard"], before, graph)
        units = package_functions(before.path, graph)
        records = run_mutants(before, after, units, gcfg, llm, limit)
        records.append(false_alarm(before, same, units, gcfg, llm))
        return records
    finally:
        for ws in (before, after, same):
            ws.close()


def swebench_target(entry: dict, cfg: dict, llm, limit: int) -> list[dict]:
    target = f"swebench:{entry['instance_id']}:{entry['agent']}"
    sandbox = cfg["core"]["sandbox"]
    before = open_workspace(target, sandbox)
    after = open_workspace(target, {**sandbox, "flaky_runs": 0})
    after.flaky = before.flaky
    try:
        graph = build_graph(before.path)
        gcfg = guard_cfg(cfg["core"]["guard"], before, graph)
        scope = agent_scope(before.path, graph)
        units = sorted(
            (
                u
                for u in graph.units()
                if u.kind == "function"
                and u.key in scope.units
                and not is_test_file(u.path)
                and not scope.outside_project(u.path)
            ),
            key=lambda u: u.key,
        )
        records = run_mutants(before, after, units, gcfg, llm, limit)
        if entry.get("differs_from_oracle"):
            records.append(patchdiff_recall(before, after, gcfg, llm))
        if units:
            records.append(false_alarm(before, after, units, gcfg, llm))
        return records
    finally:
        before.close()
        after.close()


def patchdiff_recall(before, after, cfg: dict, llm) -> dict:
    """verify(agent patch, oracle patch): does the Guard see that they behave differently?"""
    t0 = time.time()
    base = subprocess.run(
        ["git", "rev-parse", f"{after.base}~1"], cwd=after.path, capture_output=True, text=True
    ).stdout.strip()
    after.rollback(base)
    oracle = drop_files(after.row["patch"], set(patch_files(after.row["test_patch"])))
    applied = after.apply_patch(oracle)
    changed = subprocess.run(
        ["git", "diff", "--name-only", after.base], cwd=after.path, capture_output=True, text=True
    ).stdout.split()
    touched = [CodeUnit(p, "file") for p in changed if p.endswith(".py") and not is_test_file(p)]
    ok, info = verify(before, after, touched, llm, cfg) if applied else (True, {})
    after.rollback(after.base)
    return {
        "experiment": "patchdiff_recall",
        "unit": ", ".join(u.path for u in touched),
        "caught": not ok,
        "check": _check(ok, info) if applied else "oracle did not apply",
        "probe_cases": getattr(info.get("diff_check"), "n_cases", None),
        "seconds": round(time.time() - t0, 1),
    }


def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["target_set"], r["experiment"]), []).append(r)
    out = []
    for (target_set, experiment), recs in sorted(groups.items()):
        n = len(recs)
        by_tests = sum(r["check"] in ("compile", "tests") for r in recs if r["caught"])
        by_probes = sum(r["check"] == "probes" for r in recs if r["caught"])
        caught = sum(r["caught"] for r in recs)
        out.append(
            {
                "target_set": target_set,
                "experiment": experiment,
                "n": n,
                "caught": caught,
                "caught_by_tests": by_tests,
                "caught_by_probes": by_probes,
                "share_caught": round(caught / n, 3) if n else "",
                "share_by_tests": round(by_tests / n, 3) if n else "",
                "share_by_probes": round(by_probes / n, 3) if n else "",
            }
        )
    return out


def write_summary() -> None:
    rows = []
    for path in sorted(RAW.glob("*.json")):
        data = json.loads(path.read_text())
        rows += [
            {**r, "target_set": data["target_set"], "target": data["target"]}
            for r in data["records"]
        ]
    import csv

    summary = summarize(rows)
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0]) if summary else ["target_set"])
        writer.writeheader()
        writer.writerows(summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--local", nargs="*", default=[], help="local targets (toy, demo)")
    parser.add_argument("--tier", action="append", default=[], help="SWE-bench split files")
    parser.add_argument("--per-local", type=int, default=20)
    parser.add_argument("--per-patch", type=int, default=5)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config()
    llm = get_client(cfg["core"]["llm"])
    RAW.mkdir(parents=True, exist_ok=True)
    jobs = [("local", p) for p in args.local]
    for tier in args.tier:
        name = "swebench_t" + Path(tier).stem.removeprefix("swebench_tier")
        jobs += [(name, e) for e in json.loads(Path(tier).read_text())]
    for kind, job in jobs:
        if kind == "local":
            target, target_set = job, "toy" if "toy_repo" in job else "demo"
        else:
            target, target_set = f"{job['instance_id']}__{job['agent']}", kind
        out = RAW / f"{target_set}__{Path(target).name}.json"
        if out.exists() and args.resume:
            continue
        t0 = time.time()
        try:
            if kind == "local":
                records = local_target(target, cfg, llm, args.per_local)
            else:
                records = swebench_target(job, cfg, llm, args.per_patch)
        except Exception as exc:  # record and move on
            print(f"error {target}: {type(exc).__name__}: {exc}", flush=True)
            continue
        out.write_text(
            json.dumps({"target_set": target_set, "target": target, "records": records}, indent=1)
        )
        caught = sum(r["caught"] for r in records)
        print(
            f"{target_set} {target}: {len(records)} checks, {caught} caught or alarms, "
            f"{time.time() - t0:.0f}s",
            flush=True,
        )
    write_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
