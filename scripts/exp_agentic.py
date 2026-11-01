"""Agentic runs on the toy repo and the demo app, with hidden checks and the answer-key score.

    python scripts/exp_agentic.py --targets toy demo --repeats 3 --methods agentic cleansweep \
        --out results/raw/agentic_p2

Each repeat gets its own LLM cache and probe cache, so repeats are separate model runs, not
cache replays. Writes one report per run and summary.csv (hits, hidden changes, time, LLM
requests and tokens, test runs) to --out.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.loaders import outcome_score  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.core.io import save_json  # noqa: E402
from cleansweep.eval import run_hidden_checks  # noqa: E402
from cleansweep.workflow import run_sweep  # noqa: E402

TOY = ROOT / "tests" / "fixtures" / "toy_repo"
FIELDS = [
    "target",
    "method",
    "repeat",
    "hits",
    "total",
    "hidden_changed",
    "hidden_note",
    "verdict",
    "seconds",
    "llm_calls",
    "prompt_tokens",
    "completion_tokens",
    "test_runs",
    "kept",
    "rolled_back",
    "lines_removed",
    "files_removed",
]


def prepare(target: str, out: Path) -> tuple[str, Path]:
    """(path to sweep, answer key) for "toy" or "demo" (the demo app with the feature patch)."""
    if target == "toy":
        return str(TOY), TOY.parent / "toy_repo_expected.json"
    dest = out / "demo_prepared"
    if not (dest / "shop_app").exists():
        subprocess.run(
            ["bash", str(ROOT / "demo" / "prepare_demo.sh"), "--with-feature", str(dest)],
            check=True,
            capture_output=True,
        )
    return str(dest / "shop_app"), dest / "shop_app_expected.json"


def _hidden_note(hidden: dict) -> str:
    if not hidden.get("available"):
        return "no hidden tests"
    if not hidden.get("applied"):
        return "final diff did not apply"
    return ""


def run_one(target: str, method: str, repeat: int, out: Path) -> dict:
    path, key = prepare(target, out)
    caches = out / "caches" / f"{target}_{method}_r{repeat}"
    cfg = load_config(
        {
            "core": {
                "llm": {"cache_path": str(caches / "llm.sqlite")},
                "guard": {"probe_cache_dir": str(caches / "probes")},
                "agents": {"install": "off"},  # like v1's runs: the host interpreter
            }
        }
    )
    if method == "agentic":
        cfg["agent_out"] = str(out / "runs" / f"{target}_{method}_r{repeat}")
    start = time.time()
    report = run_sweep(path, cfg, method=method, seed=repeat)
    seconds = round(time.time() - start, 1)
    hidden = run_hidden_checks(path, report.stats.get("final_diff", ""), cfg)
    save_json(report, out / "reports" / f"{target}_{method}_r{repeat}.json")
    (out / "reports" / f"{target}_{method}_r{repeat}.hidden.json").write_text(
        json.dumps(hidden, default=str, indent=1)
    )
    score = outcome_score(report, key)
    s = report.stats
    return {
        "target": target,
        "method": method,
        "repeat": repeat,
        "hits": score["hits"],
        "total": score["total"],
        "hidden_changed": hidden.get("behavior_changed"),
        "hidden_note": _hidden_note(hidden),
        "verdict": s.get("agentic", {}).get("verdict", ""),
        "seconds": seconds,
        "llm_calls": s.get("llm_calls"),
        "prompt_tokens": s.get("prompt_tokens"),
        "completion_tokens": s.get("completion_tokens"),
        "test_runs": s.get("test_runs"),
        "kept": s.get("items_kept"),
        "rolled_back": s.get("items_rolled_back"),
        "lines_removed": s.get("lines_removed"),
        "files_removed": s.get("files_removed"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--targets", nargs="+", default=["toy", "demo"], choices=["toy", "demo"])
    parser.add_argument(
        "--methods", nargs="+", default=["agentic"], choices=["agentic", "cleansweep"]
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", default="results/raw/agentic_p2")
    args = parser.parse_args(argv)
    out = Path(args.out)
    (out / "reports").mkdir(parents=True, exist_ok=True)
    summary = out / "summary.csv"
    new = not summary.exists()
    with summary.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        for target in args.targets:
            for method in args.methods:
                for repeat in range(args.repeats):
                    row = run_one(target, method, repeat, out)
                    writer.writerow(row)
                    f.flush()
                    print(json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
