"""v2 evaluation runs: the agent team and its ablations (and v1's methods where needed) on the
toy repo, the demo app, SWE-bench patches and AIDev repositories, with the hidden checks.

    python scripts/experiments/v2/exp_eval.py --targets toy demo --repeats 3 \\
        --methods agentic agentic-rules agentic-single_agent --out results/raw/v2_eval/toy_demo
    python scripts/experiments/v2/exp_eval.py --split data/splits/swebench_tier1.json \\
        --methods agentic --out results/raw/v2_eval/tier1
    python scripts/experiments/v2/exp_eval.py --split data/splits/aidev_repos.json \\
        --repos shotgun-sh/shotgun ... --methods agentic --out results/raw/v2_eval/aidev

Methods are the labels of methods_v2.py. Each repeat has its own LLM and probe caches, so
repeats are separate model runs. A run writes <out>/<name>__<method>__r<k>.json (a SweepReport
with stats.hidden and stats.minutes; the toy and demo also stats.score from their answer keys)
and appends a row to <out>/runs.csv with the comparison measures: hidden behavior changed,
code lines removed (Python files that are not tests), rollbacks by tests and by probes, LLM
requests and tokens, minutes, test runs, agent steps, exhausted budgets, lessons, step-backs.
A run that already has its report is skipped, so a stopped job resumes; a failed run is logged
in <out>/errors/ and retried next time.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "v1"))

from exp_agentic import prepare  # noqa: E402
from exp_swebench import missing_history, targets  # noqa: E402
from methods_v2 import LABELS, resolve  # noqa: E402

from app.dashboard.loaders import outcome_score  # noqa: E402
from cleansweep.analysis.graph import is_test_file  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.core.io import save_json  # noqa: E402
from cleansweep.eval import run_hidden_checks  # noqa: E402
from cleansweep.workflow import run_sweep  # noqa: E402

FIELDS = [
    "target",
    "method",
    "repeat",
    "verdict",
    "hidden_changed",
    "hidden_note",
    "hits",
    "total",
    "code_lines_removed",
    "lines_removed",
    "files_removed",
    "kept",
    "rolled_back_tests",
    "rolled_back_probes",
    "rolled_back_other",
    "llm_calls",
    "prompt_tokens",
    "completion_tokens",
    "minutes",
    "test_runs",
    "agent_steps",
    "budgets_exhausted",
    "lessons",
    "back_steps",
]


def code_lines_removed(diff: str) -> int:
    """Lines removed from Python files that are not tests."""
    count, current = 0, False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = line.rsplit(" b/", 1)[-1]
            current = path.endswith(".py") and not is_test_file(path)
        elif current and line.startswith("-") and not line.startswith("---"):
            count += 1
    return count


def rollbacks(report) -> dict[str, int]:
    """Rolled-back edits by the check that failed them: tests, probes or another check."""
    out = {"tests": 0, "probes": 0, "other": 0}
    for r in report.results:
        if r.status != "rolled_back":
            continue
        if r.diff_check is not None and not r.diff_check.same or "probe" in (r.notes or ""):
            out["probes"] += 1
        elif (r.tests is not None and not r.tests.ok) or "tests failed" in (r.notes or ""):
            out["tests"] += 1
        else:
            out["other"] += 1
    return out


def measures(target: str, method: str, repeat: int, report, hidden: dict, score: dict) -> dict:
    s = report.stats
    agentic = s.get("agentic") or {}
    gone = rollbacks(report)
    stopped = agentic.get("stopped") or ""
    hidden_note = ""
    if not hidden.get("available", True):
        hidden_note = hidden.get("reason", "no hidden checks")
    elif hidden.get("applied") is False:
        hidden_note = "final diff did not apply"
    return {
        "target": target,
        "method": method,
        "repeat": repeat,
        "verdict": agentic.get("verdict", ""),
        "hidden_changed": hidden.get("behavior_changed"),
        "hidden_note": hidden_note,
        "hits": score.get("hits", ""),
        "total": score.get("total", ""),
        "code_lines_removed": code_lines_removed(s.get("final_diff", "")),
        "lines_removed": s.get("lines_removed"),
        "files_removed": s.get("files_removed"),
        "kept": s.get("items_kept", 0) + s.get("items_repaired", 0),
        "rolled_back_tests": gone["tests"],
        "rolled_back_probes": gone["probes"],
        "rolled_back_other": gone["other"],
        "llm_calls": s.get("llm_calls"),
        "prompt_tokens": s.get("prompt_tokens"),
        "completion_tokens": s.get("completion_tokens"),
        "minutes": s.get("minutes"),
        "test_runs": s.get("test_runs"),
        "agent_steps": sum(a.get("steps", 0) for a in (agentic.get("agents") or {}).values())
        if agentic
        else "",
        "budgets_exhausted": agentic.get("budget_exhausted", 0) + int("budget" in stopped)
        if agentic
        else "",
        "lessons": len(agentic.get("lessons") or []) if agentic else "",
        "back_steps": sum((agentic.get("back_steps") or {}).values()) if agentic else "",
    }


def run_one(target: str, name: str, label: str, repeat: int, out: Path, key: Path | None) -> dict:
    method, judge, agents = resolve(label)
    if judge:
        os.environ["CLEANSWEEP_JUDGE_MODE"] = judge
    else:
        os.environ.pop("CLEANSWEEP_JUDGE_MODE", None)
    caches = out / "caches" / f"{name}__{label}__r{repeat}"
    local = not target.startswith(("aidev:", "swebench:"))
    agent_cfg = {**agents, **({"install": "off", "format_policy": "always"} if local else {})}
    cfg = load_config(
        {
            "core": {
                "llm": {"cache_path": str(caches / "llm.sqlite")},
                "guard": {"probe_cache_dir": str(caches / "probes")},
                "agents": agent_cfg,
            }
        }
    )
    if method == "agentic":
        cfg["agent_out"] = str(out / "runs" / f"{name}__{label}__r{repeat}")
    t0 = time.time()
    report = run_sweep(target, cfg, method=method, seed=repeat)
    report.stats["minutes"] = round((time.time() - t0) / 60, 2)
    hidden = run_hidden_checks(target, report.stats.get("final_diff", ""), cfg)
    full = outcome_score(report, key) if key else {}
    score = {k: full[k] for k in ("hits", "total")} if full else {}
    report.stats.update(hidden=hidden, judge_mode=judge, score=score or None)
    save_json(report, out / f"{name}__{label}__r{repeat}.json")
    return measures(name, label, repeat, report, hidden, score)


def jobs(args) -> list[tuple[str, str, Path | None]]:
    """(target, name, answer key) for --targets or --split."""
    out = []
    for t in args.targets or []:
        path, key = prepare(t, Path(args.out))
        out.append((path, t, key))
    if args.split:
        entries = json.loads(Path(args.split).read_text())
        for target, name in targets(entries):
            full = target.removeprefix("aidev:").partition("@")[0]
            inst = target.split(":")[1] if target.startswith("swebench:") else None
            if args.repos and full not in args.repos and inst not in args.repos:
                continue
            out.append((target, name, None))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--targets", nargs="+", choices=["toy", "demo"])
    parser.add_argument("--split", help="a split file: data/splits/swebench_tier1.json, ...")
    parser.add_argument("--repos", nargs="+", help="only these AIDev repositories or instances")
    parser.add_argument("--methods", nargs="+", default=["agentic"], choices=LABELS)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    todo = jobs(args)
    missing = missing_history([(t, n) for t, n, _ in todo])
    if missing:
        print(f"no cached history for {', '.join(missing)}: link data/processed", file=sys.stderr)
        return 2
    runs = out / "runs.csv"
    new = not runs.exists()
    with runs.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        for target, name, key in todo:
            for label in args.methods:
                for repeat in range(args.repeats):
                    if (out / f"{name}__{label}__r{repeat}.json").exists():
                        continue
                    try:
                        row = run_one(target, name, label, repeat, out, key)
                    except Exception as exc:  # record and go on; the next run retries it
                        (out / "errors").mkdir(exist_ok=True)
                        (out / "errors" / f"{name}__{label}__r{repeat}.txt").write_text(
                            traceback.format_exc()
                        )
                        print(f"error {name} {label} r{repeat}: {type(exc).__name__}: {exc}")
                        continue
                    writer.writerow(row)
                    f.flush()
                    print(json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
