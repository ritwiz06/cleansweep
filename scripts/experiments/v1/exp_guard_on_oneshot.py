"""Guard as a filter on one-shot cleanups: verify(agent patch, agent patch + one-shot diff).

    python scripts/experiments/v1/exp_guard_on_oneshot.py [--resume] [--probe-mode runner|direct]
        [--t2-oneshot FOLDER]

The Tier 2 one-shot reports default to the run copy's raw reports in ../cleansweep-archive
(scripts/experiments/v1/archive_paths.py).

For every Tier 1 and Tier 2 patch where one_shot_llm applied edits, the agent patch is the
before version and the agent patch plus one-shot's final diff is the after version. verify runs
the tests and then the probes on the changed files (runner mode unless --probe-mode says
otherwise). A run whose hidden checks changed is a breakage the Guard should block; a block on
any other run is a false alarm. The Tier 1 patches are also in Tier 2: a diff that is the same in
both is verified once and reported for both.

One JSON per patch and diff in results/raw/guard_on_oneshot/, one row per run in
results/summary/guard_on_oneshot.csv and a summary in guard_on_oneshot.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_paths import check_defaults  # noqa: E402
from exp_guard_strength import _check, _mismatches, guard_cfg  # noqa: E402
from exp_oneshot_breakages import T2, diff_files, report_path, targets  # noqa: E402

from cleansweep.analysis import build_graph  # noqa: E402
from cleansweep.analysis.graph import is_test_file  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.core.models import CodeUnit  # noqa: E402
from cleansweep.guard import verify  # noqa: E402
from cleansweep.llm import get_client  # noqa: E402
from cleansweep.sandbox import open_workspace  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "results" / "raw" / "guard_on_oneshot"
SUMMARY = ROOT / "results" / "summary" / "guard_on_oneshot"
FIELDS = [
    "target_set",
    "target",
    "edits_applied",
    "hidden_changed",
    "applied",
    "blocked",
    "check",
    "probe_cases",
    "probe_mode",
    "new_failures",
    "mismatches",
    "seconds",
]


def one_shot_runs() -> list[dict]:
    """Tier 1 and Tier 2 one_shot_llm runs that applied edits."""
    runs = []
    for target_set in ("swebench_t1", "swebench_t2"):
        for target in targets(target_set):
            path = report_path(target_set, target, "one_shot_llm")
            if path is None:
                continue
            data = json.loads(path.read_text())
            edits = sum(r["status"] == "kept" and bool(r["diff"].strip()) for r in data["results"])
            diff = data["stats"].get("final_diff", "")
            if edits and diff.strip():
                hidden = data["stats"].get("hidden") or {}
                runs.append(
                    {
                        "target_set": target_set,
                        "target": target,
                        "edits_applied": edits,
                        "hidden_changed": int(bool(hidden.get("behavior_changed"))),
                        "diff": diff,
                    }
                )
    return runs


def touched_units(diff: str) -> list[CodeUnit]:
    """Changed and deleted Python files outside the tests, as file units."""
    return [
        CodeUnit(f["path"], "file")
        for f in diff_files(diff)
        if f["path"].endswith(".py") and not is_test_file(f["path"])
    ]


def check_patch(target: str, diff: str, cfg: dict, llm) -> dict:
    instance, agent = target.rsplit("__", 1)
    name = f"swebench:{instance}:{agent}"
    sandbox = cfg["core"]["sandbox"]
    before = open_workspace(name, sandbox)
    after = open_workspace(name, {**sandbox, "flaky_runs": 0})
    after.flaky = before.flaky
    t0 = time.time()
    try:
        graph = build_graph(before.path)
        gcfg = guard_cfg(cfg["core"]["guard"], before, graph)
        if not after.apply_patch(diff):
            return {"applied": False, "blocked": None, "check": "diff did not apply"}
        ok, info = verify(before, after, touched_units(diff), llm, gcfg)
        return {
            "applied": True,
            "blocked": not ok,
            "check": _check(ok, info),
            "probe_cases": getattr(info.get("diff_check"), "n_cases", None),
            "probe_mode": info.get("probe_mode"),
            "new_failures": sorted(info.get("new_failures") or [])[:5],
            "mismatches": _mismatches(info),
            "seconds": round(time.time() - t0, 1),
        }
    finally:
        before.close()
        after.close()


def write_summary(rows: list[dict]) -> None:
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY.with_suffix(".csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {k: "; ".join(r[k]) if isinstance(r.get(k), list) else r.get(k) for k in FIELDS}
            )
    md = [
        "# Guard on one-shot cleanups",
        "",
        "verify(agent patch, agent patch + one_shot_llm diff), tests then probes.",
        "",
        "| target set | runs with edits | hidden changed: blocked | by compile | by tests "
        "| only by probes | hidden unchanged: blocked (false alarms) |",
        "|---|---|---|---|---|---|---|",
    ]
    for target_set in ("swebench_t1", "swebench_t2"):
        mine = [r for r in rows if r["target_set"] == target_set and r.get("applied")]
        broke = [r for r in mine if r["hidden_changed"]]
        fine = [r for r in mine if not r["hidden_changed"]]
        blocked = [r for r in broke if r["blocked"]]
        by = {c: sum(r["check"] == c for r in blocked) for c in ("compile", "tests", "probes")}
        alarms = sum(bool(r["blocked"]) for r in fine)
        md.append(
            f"| {target_set} | {len(mine)} | {len(blocked)}/{len(broke)} | {by['compile']} | "
            f"{by['tests']} | {by['probes']} | {alarms}/{len(fine)} |"
        )
    SUMMARY.with_suffix(".md").write_text("\n".join(md) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--probe-mode", choices=["direct", "runner"], default="runner")
    parser.add_argument("--t2-oneshot", default=str(T2["t2_oneshot"]))
    args = parser.parse_args(argv)
    check_defaults("exp_guard_on_oneshot.py", parser, args, ["--t2-oneshot"])
    T2["t2_oneshot"] = Path(args.t2_oneshot)
    cfg = load_config()
    cfg["core"]["guard"]["probe_mode"] = args.probe_mode
    llm = get_client(cfg["core"]["llm"])
    RAW.mkdir(parents=True, exist_ok=True)
    rows, fresh = [], set()
    for run in one_shot_runs():
        digest = hashlib.sha256(run["diff"].encode()).hexdigest()[:10]
        out = RAW / f"{run['target']}__{digest}.json"
        done = json.loads(out.read_text()) if out.exists() else {}
        if not (done and (args.resume or out in fresh)):
            try:
                result = check_patch(run["target"], run["diff"], cfg, llm)
            except Exception as exc:  # record and move on
                print(f"error {run['target']}: {type(exc).__name__}: {exc}", flush=True)
                continue
            done = {"target": run["target"], "diff": run["diff"], "result": result}
            out.write_text(json.dumps(done, indent=1))
            fresh.add(out)
            print(f"{run['target_set']} {run['target']}: {result}", flush=True)
        meta = {k: v for k, v in run.items() if k != "diff"}
        rows.append(meta | done["result"])
    write_summary(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
