"""Probe strength in v2: the mutation score and PatchDiff recall of the coverage-guided probes,
on the same mutants and patches as v1's exp_guard_strength.py.

    python scripts/experiments/v2/exp_probe_strength.py --local tests/fixtures/toy_repo \\
        .cleansweep/demo/shop_app --tier data/splits/swebench_tier1.json \\
        --tier data/splits/swebench_tier2_v2subset.json [--experiments mutation recall] [--resume]

It runs v1's experiment with one change: after v1's compile and test checks (its own probes
off), a change they miss goes to the coverage-guided probes the v2 Validator runs (rounds until
the changed lines are covered, at most 3; coverage target 0.9). Mutants are sampled exactly as
v1 samples them (same seed and limits), so the two can be compared mutant by mutant. Records go
to results/raw/probe_strength/ in v1's format, and results/summary/v2/probe_strength.csv
summarizes them. v1's false-alarm experiment has no v2 counterpart: the coverage-guided probes
run only on changed code, so two identical copies get no probes at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent / "v1"))

import exp_guard_strength as v1  # noqa: E402

from cleansweep.agents.coverage_probes import probe_with_coverage  # noqa: E402
from cleansweep.guard.difftest import probe_mode  # noqa: E402

v1.RAW = ROOT / "results" / "raw" / "probe_strength"
v1.SUMMARY = ROOT / "results" / "summary" / "v2" / "probe_strength.csv"
v1.EXPERIMENTS = ("mutation", "recall")
_v1_verify = v1.verify


def verify(before, after, touched, llm, cfg: dict) -> tuple[bool, dict]:
    """v1's compile and test checks, then the coverage-guided probes on what they miss."""
    ok, info = _v1_verify(before, after, touched, llm, {**cfg, "diff_tests": False})
    if not ok or cfg.get("format_only"):
        return ok, info
    outcome, extra = probe_with_coverage(
        after, after.base, cfg.get("items", []), cfg["graph"], llm, cfg
    )
    info.update(
        diff_check=outcome,
        probe_mode=probe_mode(after, cfg),
        coverage=extra.get("coverage"),
        probe_rounds=extra.get("rounds"),
    )
    if outcome is not None and not outcome.same:
        info["check"] = "probes"
        return False, info
    return True, info


v1.verify = verify

if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--experiments" not in argv:
        argv += ["--experiments", *v1.EXPERIMENTS]
    raise SystemExit(v1.main(argv))
