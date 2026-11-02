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

    python scripts/experiments/v2/exp_probe_strength.py --compare

writes results/summary/v2/probe_strength_vs_v1.csv: the same mutants and patches, matched by
target, unit, operator and line, caught by v1's probes (results/raw/guard_strength/) and by these.
"""

from __future__ import annotations

import csv
import json
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

V1_RAW = ROOT / "results" / "raw" / "guard_strength"
COMPARE = ROOT / "results" / "summary" / "v2" / "probe_strength_vs_v1.csv"


def _records(folder: Path) -> dict[tuple, dict]:
    """(target set, target, probe mode, experiment, unit, operator, line, n) -> record; n counts
    mutants with the same operator on the same line (both versions sample them in one order)."""
    out: dict[tuple, dict] = {}
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text())
        target_set = data["target_set"].removesuffix("_v2subset")  # v1's tier name
        mode = data.get("probe_mode", "direct")
        for r in data["records"]:
            key = (target_set, data["target"], mode, r["experiment"])
            key += (r.get("unit"), r.get("operator"), r.get("line"))
            n = sum(k[:-1] == key for k in out)
            out[(*key, n)] = r
    return out


def compare(v1_raw: Path = V1_RAW, v2_raw: Path = v1.RAW) -> list[dict]:
    """Per target set and experiment: what v1's probes and the coverage-guided probes catch on
    the same mutants and patches."""
    old, new = _records(v1_raw), _records(v2_raw)
    groups: dict[tuple, dict] = {}
    for key, r in new.items():
        g = groups.setdefault(
            (key[0], key[3], key[2]),
            {"matched": 0, "both": 0, "only_v1": 0, "only_v2": 0, "neither": 0, "v2_only_run": 0},
        )
        if key not in old:
            g["v2_only_run"] += 1
            continue
        g["matched"] += 1
        a, b = bool(old[key]["caught"]), bool(r["caught"])
        g["both" if a and b else "only_v1" if a else "only_v2" if b else "neither"] += 1
    return [
        {"target_set": t, "experiment": e, "probe_mode": m, **g}
        for (t, e, m), g in sorted(groups.items())
    ]


def write_compare() -> None:
    rows = compare()
    COMPARE.parent.mkdir(parents=True, exist_ok=True)
    with COMPARE.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["target_set"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} rows; {COMPARE}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv == ["--compare"]:
        write_compare()
        raise SystemExit(0)
    if "--experiments" not in argv:
        argv += ["--experiments", *v1.EXPERIMENTS]
    raise SystemExit(v1.main(argv))
