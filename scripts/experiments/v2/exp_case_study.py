"""A real-project case study: `clean` a project with the real model and record the outcome.

    python scripts/experiments/v2/exp_case_study.py PATH --name NAME [--exclude FOLDER ...]
        [--test-args "..."] [--runs-dir ../case_studies/runs] [--mode safe|thorough]

The clean output (workspace with the branch, report files) goes to --runs-dir/NAME (outside
the project). An "aidev:owner/name@sha" target (an untrusted repository) runs only inside its
network-less container, through run_sweep(method="agentic"), with the whole project in scope.

The record goes to results/raw/case_studies/NAME/: summary.json (brief, candidates by category
and decision, packages by outcome, lines and files removed, tests before and after, probe
coverage, LLM requests and tokens, time, lessons), diffstat.txt, and copies of
CLEANUP_REPORT.md, blueprint.md, report.json and events.jsonl.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from cleansweep.agents import clean_project  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402

COPY = ["CLEANUP_REPORT.md", "blueprint.md", "PR_DESCRIPTION.md", "report.json", "events.jsonl"]


def record(result: dict, seconds: float) -> dict:
    """The case-study numbers, from the run's report and events."""
    report = result["report"]
    agentic = report.stats["agentic"]
    status = {r.item_id: r.status for r in report.results}
    by_cat: dict[str, Counter] = {}
    for item in report.plan.items:
        by_cat.setdefault(item.category, Counter())[status.get(item.item_id, "-")] += 1
    events = [
        json.loads(line) for line in Path(result["out"], "events.jsonl").read_text().splitlines()
    ]
    coverage = [
        e["payload"]["coverage"]
        for e in events
        if e["kind"] == "check" and e["payload"].get("check") == "probe coverage"
    ]
    brief = next(
        (e["payload"]["result"] for e in events if e["payload"].get("tool") == "project_facts"), {}
    )
    return {
        "project": report.repo_id,
        "verdict": result["summary"]["verdict"],
        "seconds": round(seconds, 1),
        "brief": brief,
        "candidates": len(report.plan.items),
        "by_category": {c: dict(n) for c, n in sorted(by_cat.items())},
        "decisions": agentic["decisions"],
        "packages": dict(Counter(p["status"] for p in agentic["packages"])),
        "lines_removed": report.stats["lines_removed"],
        "files_removed": report.stats["files_removed"],
        "tests_before": agentic["baseline"],
        "tests_after": agentic["final"],
        "probe_coverage": coverage,
        "llm_requests": report.stats["llm_calls"],
        "prompt_tokens": report.stats["prompt_tokens"],
        "completion_tokens": report.stats["completion_tokens"],
        "test_runs": report.stats["test_runs"],
        "phases": agentic["phases"],
        "phase_seconds": agentic["phase_seconds"],
        "back_steps": agentic["back_steps"],
        "lessons": agentic["lessons"],
        "agents": agentic["agents"],
        "branch": result["branch"],
        "workspace": result["workspace"],
    }


def run_container(args, out: Path) -> dict:
    """An untrusted repository runs only inside the AIDev container (network off for the
    tests): the agent team via run_sweep(method="agentic"), the whole project in scope."""
    from cleansweep.core.io import save_json
    from cleansweep.workflow import run_sweep

    cfg = load_config({"reviewer": {"scope": "repo"}})
    cfg["agent_out"] = str(out)
    out.mkdir(parents=True, exist_ok=True)
    report = run_sweep(args.path, cfg, method="agentic")
    save_json(report, out / "report.json")
    agentic = report.stats["agentic"]
    return {
        "out": str(out),
        "report": report,
        "summary": {"verdict": agentic["verdict"]},
        "branch": None,
        "workspace": None,
        "base": None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path")
    parser.add_argument("--name", required=True)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--test-args")
    parser.add_argument("--mode", default="safe", choices=["safe", "thorough"])
    parser.add_argument("--runs-dir", default=str(ROOT.parent / "case_studies" / "runs"))
    args = parser.parse_args(argv)
    out = Path(args.runs_dir) / args.name
    dest = ROOT / "results" / "raw" / "case_studies" / args.name
    dest.mkdir(parents=True, exist_ok=True)
    start = time.time()
    if args.path.startswith("aidev:"):
        result = run_container(args, out)
        summary = record(result, time.time() - start)
        stat = subprocess.run(
            ["git", "apply", "--stat", "-"],
            input=result["report"].stats["final_diff"],
            capture_output=True,
            text=True,
        )
        (dest / "diffstat.txt").write_text(stat.stdout)
        (dest / "final.diff").write_text(result["report"].stats["final_diff"])
        for name in COPY:
            if (out / name).exists():
                shutil.copy(out / name, dest / name)
        (dest / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
        print(
            json.dumps(
                {
                    k: summary[k]
                    for k in (
                        "verdict",
                        "seconds",
                        "candidates",
                        "packages",
                        "lines_removed",
                        "files_removed",
                        "llm_requests",
                    )
                }
            )
        )
        return 0 if summary["verdict"] in ("everything runs", "nothing applied") else 1
    result = clean_project(
        args.path,
        load_config(),
        out=str(out),
        mode=args.mode,
        on_event=lambda e: (
            print(f"-> {e['payload']['to']}: {e['payload']['reason']}", flush=True)
            if e["kind"] == "phase_change"
            else None
        ),
        test_args=shlex.split(args.test_args) if args.test_args else None,
        exclude=[e.rstrip("/") + "/" for e in args.exclude],
    )
    summary = record(result, time.time() - start)
    for name in COPY:
        if (out / name).exists():
            shutil.copy(out / name, dest / name)
    if result["branch"]:
        stat = subprocess.run(
            ["git", "diff", "--stat", f"{result['base']}..{result['branch']}"],
            cwd=result["workspace"],
            capture_output=True,
            text=True,
        )
        (dest / "diffstat.txt").write_text(stat.stdout)
    (dest / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "verdict",
                    "seconds",
                    "candidates",
                    "packages",
                    "lines_removed",
                    "files_removed",
                    "llm_requests",
                )
            }
        )
    )
    return 0 if summary["verdict"] in ("everything runs", "nothing applied") else 1


if __name__ == "__main__":
    sys.exit(main())
