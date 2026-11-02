"""Manager decision scenarios: four small projects where the Manager's choice matters, each with
its right answer written down, run with the LLM-guided Manager and with the rule-based one.

    python scripts/experiments/v2/exp_manager_scenarios.py [--repeats 3] [--managers llm rules]
    python scripts/experiments/v2/exp_manager_scenarios.py --table

The other agents run without an LLM (their rule-based paths), so every run reaches the same
decision point; only the Manager's choice differs. The LLM Manager uses the agents' model with a
fresh reply cache per repeat. Fixtures: tests/fixtures/scenarios/<scenario>/.

- rollbacks: two of the first three packages roll back (an import with a side effect, a
  leftover file a test loads by name) and packages are left. Right: go back to INVESTIGATE or
  replan, so the lessons shape the rest.
- conflict: two leftover files can each go, but a test needs one of them; the per-package checks
  run only related tests, so the final suite fails. Right: go back to EXECUTE and undo the last
  package (the conflict), keeping the other; undoing everything is not.
- budget: 8 of 9 test runs used with one package left. Right: stop and deliver the verified
  packages, so FINAL VERIFY still fits in the cap (stopping before any package delivers
  nothing and is not right).
- no_baseline: the test command fails to run (a conftest import error). Right: change nothing
  (stop, or deliver the plan only) and say why in the report.

Writes the runs to results/raw/manager_scenarios/<scenario>/<manager>-r<k>/ and
results/summary/v2/manager_scenarios.csv: per scenario and Manager, decision accuracy against
the right answer, outcomes never worse than the baseline, test runs against the cap, the
Manager's LLM requests, tokens and time.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from cleansweep.agents import clean_project  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.workflow.sweep import make_llm  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "scenarios"
RAW = ROOT / "results" / "raw" / "manager_scenarios"
OUT = ROOT / "results" / "summary" / "v2" / "manager_scenarios.csv"
SCENARIOS = {
    "rollbacks": {
        "agents": {"format_policy": "always"},
        "expected": "go back to INVESTIGATE or replan once half the packages rolled back",
    },
    "conflict": {
        "agents": {"full_suite_max_s": 0},
        "expected": "go back to EXECUTE and undo only the conflicting package",
    },
    "budget": {
        "agents": {"budget": {"test_runs": 9, "llm_calls": 0, "minutes": 0}},
        "expected": "stop at 85% of the test-run cap and deliver the verified packages",
    },
    "no_baseline": {
        "agents": {},
        "expected": "change nothing (stop or plan only) and report why",
    },
}


def events(out: Path) -> list[dict]:
    return [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines()]


def judge(scenario: str, report: dict, evs: list[dict]) -> tuple[bool, str]:
    """(right answer?, what the Manager did) for one run."""
    agentic = report["stats"]["agentic"]
    status = Counter(p["status"] for p in agentic["packages"])
    backs = [
        (e["payload"]["from"], e["payload"]["to"])
        for e in evs
        if e["kind"] == "phase_change" and e["payload"].get("back")
    ]
    stops = [
        e
        for e in evs
        if e["kind"] == "decision" and e["payload"].get("text", "").startswith("stopping early")
    ]
    if scenario == "rollbacks":
        went_back = [b for b in backs if b[1] in ("PLAN", "INVESTIGATE") and b[0] != "BASELINE"]
        did = f"went back to {went_back[0][1]}" if went_back else "went on"
        return bool(went_back), did
    if scenario == "conflict":
        did = f"kept {status['kept']}, undid {status['reverted']}"
        return status["kept"] == 1 and status["reverted"] == 1 and agentic["final"]["ok"], did
    if scenario == "budget":
        cap = SCENARIOS["budget"]["agents"]["budget"]["test_runs"]
        within = report["stats"]["test_runs"] <= cap
        kept = status["kept"] + status["repaired"]
        did = ("stopped" if stops else "went on") + f", kept {kept}"
        did += f", {report['stats']['test_runs']} test runs"
        return bool(stops) and within and kept > 0, did
    applied = status["kept"] + status["repaired"]
    did = "stopped" if stops else "planned only"
    return applied == 0 and agentic["verdict"] == "nothing applied", did


def run_one(scenario: str, manager: str, repeat: int) -> dict:
    out = RAW / scenario / f"{manager}-r{repeat}"
    if out.exists():
        shutil.rmtree(out)
    agents = {"install": "off", "baseline_runs": 3, "manager": manager}
    agents |= SCENARIOS[scenario]["agents"]
    cfg = load_config(
        {
            "core": {
                "agents": agents,
                "sandbox": {"work_dir": str(RAW / "ws")},
                "llm": {"cache_path": str(RAW / f"llm_cache_r{repeat}.sqlite")},
            }
        }
    )
    llm = make_llm(cfg["core"]) if manager == "llm" else None
    start = time.time()
    result = clean_project(
        str(FIXTURES / scenario), cfg, out=str(out), use_llm=False, manager_llm=llm
    )
    seconds = time.time() - start
    report = json.loads((out / "report.json").read_text())
    evs = events(out)
    right, did = judge(scenario, report, evs)
    agentic = report["stats"]["agentic"]
    choices = [
        e["payload"]["choice"] for e in evs if e["kind"] == "decision" and "choice" in e["payload"]
    ]
    return {
        "scenario": scenario,
        "manager": manager,
        "repeat": repeat,
        "right": right,
        "did": did,
        "choices": choices,
        "verdict": agentic["verdict"],
        "never_worse": agentic["verdict"] in ("everything runs", "nothing applied"),
        "test_runs": report["stats"]["test_runs"],
        "llm_requests": report["stats"]["llm_calls"],
        "tokens": report["stats"]["prompt_tokens"] + report["stats"]["completion_tokens"],
        "seconds": round(seconds, 1),
        "branch": result["branch"],
    }


def table(rows: list[dict]) -> Path:
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["scenario"], row["manager"]), []).append(row)
    lines = []
    for (scenario, manager), runs in sorted(
        groups.items(), key=lambda kv: (list(SCENARIOS).index(kv[0][0]), kv[0][1])
    ):
        lines.append(
            {
                "scenario": scenario,
                "expected": SCENARIOS[scenario]["expected"],
                "manager": manager,
                "runs": len(runs),
                "right": sum(r["right"] for r in runs),
                "accuracy": round(sum(r["right"] for r in runs) / len(runs), 3),
                "what_it_did": "; ".join(sorted(set(r["did"] for r in runs))),
                "never_worse": sum(r["never_worse"] for r in runs),
                "test_runs_median": statistics.median(r["test_runs"] for r in runs),
                "llm_requests_median": statistics.median(r["llm_requests"] for r in runs),
                "tokens_median": statistics.median(r["tokens"] for r in runs),
                "seconds_median": statistics.median(r["seconds"] for r in runs),
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(lines[0]))
        writer.writeheader()
        writer.writerows(lines)
    return OUT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--managers", nargs="+", default=["llm", "rules"])
    parser.add_argument("--scenarios", nargs="+", default=list(SCENARIOS))
    parser.add_argument("--table", action="store_true", help="rebuild the table from the runs")
    args = parser.parse_args(argv)
    runs = RAW / "runs.json"
    rows = json.loads(runs.read_text()) if runs.exists() else []
    if not args.table:
        done = {(r["scenario"], r["manager"], r["repeat"]) for r in rows}
        for scenario in args.scenarios:
            for manager in args.managers:
                for repeat in range(1, args.repeats + 1):
                    if (scenario, manager, repeat) in done:
                        continue
                    row = run_one(scenario, manager, repeat)
                    rows.append(row)
                    runs.parent.mkdir(parents=True, exist_ok=True)
                    runs.write_text(json.dumps(rows, indent=1))
                    print(
                        json.dumps(
                            {k: row[k] for k in ("scenario", "manager", "repeat", "right", "did")}
                        )
                    )
    print(table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
