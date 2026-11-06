"""The audit-miss estimate. v2's diff audit checked only the kept code edits its auditor voted
"yes" or "unsure", so its wrong-edit counts are lower bounds. This draws "no"-voted edits of the
four main methods, gives each a targeted test (run before and after the edit in the run's own
environment, with exp_audit_confirm.py's machinery) and a reading under the audit's rubric, and
estimates the share of wrong edits among the unflagged ones. Measured on v2's edits (the auditor
and its rubric are unchanged in v3); every rate and corrected count it reports is an estimate.

    python scripts/experiments/v3/exp_audit_miss.py sample
    python scripts/experiments/v3/exp_audit_miss.py run [--edits ID ...]
    python scripts/experiments/v3/exp_audit_miss.py table

sample: the "no"-voted kept code edits (exp_diff_audit.py's edits: identical edits merged) of the
team (agentic), the team without the research squad, the single agent and v1's gatekeeper
(cleansweep on the injected set), 25 per method (all of them when a method has fewer), seed 572.
Within a method the draw is proportional to the target sets (injected, real projects, answer keys
and SWE-bench, AIDev; largest remainder, at least one from each set that has any), and each edit
stands for weight = population / sampled edits of its set. An edit drawn for two methods is
tested once. Writes results/raw/audit_miss/sample.json.
run: each sampled edit with results/raw/audit_miss/tests/<edit>/test_<edit>.py (and hide.txt for
a dependency removal) runs its test before and after the edit, as exp_audit_confirm.py runs v2's;
an edit with no_test.txt (why no test can be written) is not run. Resumable (--edits reruns those);
one workspace at a time, waiting while the load is high. Writes results/raw/audit_miss/
results.json.
table: results/summary/v3/audit_miss.csv, per method and overall, in two tiers: confirmed (the
test passes before and fails after the edit, and the reading calls the edit wrong) and reading
(LLM-judged: results/raw/audit_miss/readings.jsonl, one JSON line per edit with verdict, evidence
and kind). The injection key settles every "no"-voted injected edit that removes a planted trap,
so those are counted (trap_census, kept code edits), not estimated: sampled trap removals leave
the estimate and the other sampled edits of their target set stand for its other "no"-voted
edits. Each row: the sampled edits, tests written, wrong edits, the census, the miss rate among
the other "no"-voted kept code edits (weighted to the method's population) with a 95% Wilson
interval at Kish's effective sample size, and the corrected wrong-edit count: v2's wrong edits
(confirmed and reading, diff_audit.csv), plus the census, plus the miss rate times the other
"no"-voted kept code edits.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "experiments" / "v2"))

import exp_audit_confirm as confirm  # noqa: E402
from exp_diff_audit import OUT as AUDIT  # noqa: E402
from exp_diff_audit import SUMMARY as V2_SUMMARY  # noqa: E402
from exp_diff_audit import collect, plant_lines, plant_rule  # noqa: E402

from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.sandbox import open_workspace  # noqa: E402
from cleansweep.sandbox.cleanup import on_start  # noqa: E402

RAW = ROOT / "results" / "raw" / "audit_miss"
TESTS = RAW / "tests"
SAMPLE = RAW / "sample.json"
RESULTS = RAW / "results.json"
READINGS = RAW / "readings.jsonl"
TABLE = ROOT / "results" / "summary" / "v3" / "audit_miss.csv"
SEED = 572
PER_METHOD = 25
# v2's method labels; v1's gatekeeper is "cleansweep" on the injected set
METHODS = {
    "agentic": "agentic",
    "agentic-no_research": "agentic-no_research",
    "agentic-single_agent": "agentic-single_agent",
    "cleansweep": "cleansweep-gatekeeper",
    "cleansweep-gatekeeper": "cleansweep-gatekeeper",
}
TARGET_SETS = {
    "injected": "injected",
    "case studies": "real projects",
    "real-project ablation": "real projects",
    "answer keys": "answer keys and SWE-bench",
    "swebench_t1": "answer keys and SWE-bench",
    "swebench_t2": "answer keys and SWE-bench",
    "aidev": "AIDev",
    "aidev after #124": "AIDev",
}
TIERS = ("confirmed", "reading (LLM-judged)")
Z = 1.96


def population(rows: list[dict], audit: dict) -> dict[tuple[str, str], dict[str, int]]:
    """(method, target set) -> {"no"-voted edit: how many of the method's kept code edits it is}."""
    out: dict[tuple[str, str], dict[str, int]] = {}
    for r in rows:
        method = METHODS.get(r["method"])
        if method is None or audit.get(r["edit"], {}).get("answer") != "no":
            continue
        cell = out.setdefault((method, TARGET_SETS[r["source"]]), {})
        cell[r["edit"]] = cell.get(r["edit"], 0) + 1
    return out


def allocate(sizes: dict[str, int], n: int) -> dict[str, int]:
    """How many edits to draw from each target set: proportional to its size (largest
    remainder), at least one from each set that has any; all of them when there are n or fewer."""
    total = sum(sizes.values())
    if total <= n:
        return dict(sizes)
    quota = {s: n * k / total for s, k in sizes.items()}
    out = {s: int(q) for s, q in quota.items()}
    for s in sorted(quota, key=lambda s: (out[s] - quota[s], s))[: n - sum(out.values())]:
        out[s] += 1
    for s in sorted(sizes):
        if sizes[s] and not out[s]:
            out[max(sorted(out), key=out.get)] -= 1
            out[s] = 1
    return out


def trap_removals(edits: dict, audit: dict) -> set[str]:
    """The "no"-voted injected edits the injection key's rule calls wrong: they remove a trap."""
    keys, out = {}, set()
    for edit_id, edit in edits.items():
        folder = Path(edit["report"]).parent
        if audit.get(edit_id, {}).get("answer") != "no" or folder.parent.name != "inject":
            continue
        if folder not in keys:
            keys[folder] = plant_lines(json.loads((folder / "key.json").read_text()))
        if plant_rule(edit["diff"], *keys[folder]) == "wrong":
            out.add(edit_id)
    return out


def draw(pop: dict[tuple[str, str], dict[str, int]], edits: dict, traps: set = frozenset()) -> dict:
    """The stratified sample: each cell's sizes (and its edits that remove a trap: unique, and as
    kept code edits), and each drawn edit with its cell, weight and whether it removes a trap."""
    strata, picked = [], []
    for method in sorted({m for m, _ in pop}):
        cells = {s: cell for (m, s), cell in pop.items() if m == method}
        take = allocate({s: len(cell) for s, cell in cells.items()}, PER_METHOD)
        for target_set in sorted(cells):
            cell, n = cells[target_set], take[target_set]
            size = {"population": len(cell), "kept": sum(cell.values()), "sampled": n}
            size["trap_edits"] = sum(e in traps for e in cell)
            size["traps"] = sum(k for e, k in cell.items() if e in traps)
            strata.append({"method": method, "target_set": target_set, **size})
            rng = random.Random(f"{SEED}:{method}:{target_set}")
            for edit in rng.sample(sorted(cell), n):
                picked.append(
                    {
                        "edit": edit,
                        "method": method,
                        "target_set": target_set,
                        "project": edits[edit]["project"],
                        "path": edits[edit]["path"],
                        "population": len(cell),
                        "sampled": n,
                        "weight": len(cell) / n,
                        "kept": cell[edit],
                        "trap": edit in traps,
                    }
                )
    return {"seed": SEED, "per_method": PER_METHOD, "strata": strata, "edits": picked}


def sample() -> Path:
    edits, rows = collect()
    audit = json.loads((AUDIT / "audit.json").read_text())
    out = draw(population(rows, audit), edits, trap_removals(edits, audit))
    for method in sorted({s["method"] for s in out["strata"]}):
        n = sum(s["sampled"] for s in out["strata"] if s["method"] == method)
        if n < PER_METHOD:
            print(f"{method}: only {n} no-voted edits, all taken")
    RAW.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_text(json.dumps(out, indent=1))
    return SAMPLE


def opened(record: dict) -> tuple[str, dict]:
    """As exp_audit_confirm.opened; a SWE-bench target opens in its own container."""
    if record["project"].startswith("swebench:"):
        # the flaky-test baseline is for the instance's suite; a targeted test does not need it
        sandbox = {**(load_config()["core"].get("sandbox") or {}), "flaky_runs": 0}
        return record["project"], sandbox
    return confirm.opened(record["project"], Path(record["report"]))


def workspace_key(record: dict) -> str:
    """Edits that open the same workspace. The injected toy repository is "local:repo" on every
    seed, so its run folder (one per seed) is part of the key."""
    report = Path(record["report"])
    key = f"{record['project']}|{report.parent.parent.name}"
    return f"{key}|{report.parent.name}" if record["project"] == "local:repo" else key


def run(only: list[str] | None = None) -> Path:
    edits, _ = collect()
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    groups: dict[str, list[dict]] = {}
    for edit in sorted({e["edit"] for e in json.loads(SAMPLE.read_text())["edits"]}):
        if not (TESTS / edit / f"test_{edit}.py").exists():
            continue
        if (only and edit not in only) or (not only and edit in results):
            continue
        record = {**edits[edit], "edit": edit}
        groups.setdefault(workspace_key(record), []).append(record)
    for key, records in groups.items():
        confirm._wait_for_load()
        target, sandbox = opened(records[0])
        print(f"open {key} ({len(records)} edits)", flush=True)
        try:
            ws = open_workspace(target, sandbox)
        except Exception as exc:  # an install that fails is a result too
            for record in records:
                results[record["edit"]] = {"error": str(exc)[:300], "confirmed": False}
            confirm._drop_copies()
            continue
        try:
            base = ws.checkpoint("audit miss base")
            for record in records:
                out = confirm.check_edit(ws, base, TESTS / record["edit"], record)
                results[record["edit"]] = {"target": target, **out}
                print(f"  {record['edit']} fails after={out['confirmed']}", flush=True)
                RESULTS.write_text(json.dumps(results, indent=1))
        finally:
            ws.close()
            confirm._drop_copies()
    RESULTS.write_text(json.dumps(results, indent=1))
    return RESULTS


def wilson(p: float, n: float) -> tuple[float, float]:
    """The 95% Wilson score interval of a share p over n trials (n may be an effective size)."""
    if n <= 0:
        return 0.0, 1.0
    centre = p + Z * Z / (2 * n)
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return max(0.0, (centre - half) / (1 + Z * Z / n)), min(1.0, (centre + half) / (1 + Z * Z / n))


def estimate(rows: list[dict], hits: list[bool]) -> tuple[float, float, float]:
    """(rate, CI low, CI high) of hits per kept code edit: each sampled edit counts weight times
    as often as the method kept it, Wilson at Kish's effective sample size."""
    w = [r["weight"] * r["kept"] for r in rows]
    if not w:
        return 0.0, 0.0, 1.0
    rate = sum(x for x, hit in zip(w, hits, strict=True) if hit) / sum(w)
    low, high = wilson(rate, sum(w) ** 2 / sum(x * x for x in w))
    return rate, low, high


def v2_wrong(path: Path = V2_SUMMARY / "diff_audit.csv") -> dict[str, tuple[int, int]]:
    """method -> (wrong edits confirmed, by reading) in v2's diff audit, over every target set."""
    out: dict[str, tuple[int, int]] = {}
    with path.open() as f:
        for r in csv.DictReader(f):
            method = METHODS.get(r["method"])
            if method:
                c, rd = out.get(method, (0, 0))
                out[method] = (c + int(r["wrong_confirmed"]), rd + int(r["wrong_reading"]))
    return out


def folders(edits: set[str]) -> dict[str, str]:
    """edit -> "test", "no_test" or "" (nothing written yet)."""
    out = {}
    for edit in edits:
        folder = TESTS / edit
        test = (folder / f"test_{edit}.py").exists()
        out[edit] = "test" if test else "no_test" if (folder / "no_test.txt").exists() else ""
    return out


def rest_weights(sample: dict) -> dict[tuple[str, str], float]:
    """(method, target set) -> the weight of a sampled edit that removes no trap: the cell's other
    "no"-voted edits over its sampled ones. Trap removals are counted (trap_census), not
    estimated, so sampled ones leave the estimate."""
    out = {}
    for s in sample["strata"]:
        key = (s["method"], s["target_set"])
        n = sum((e["method"], e["target_set"]) == key and not e["trap"] for e in sample["edits"])
        out[key] = (s["population"] - s["trap_edits"]) / n if n else 0.0
    return out


def tier_row(tier: str, mine: list[dict], strata: list[dict], v2: tuple[int, int]) -> dict:
    """One method's (or all methods') row of a tier. mine: sampled edits with written, changed,
    verdict and the weight among the edits that remove no trap filled in."""
    if tier == "confirmed":
        hits = [r["changed"] and r["verdict"] == "wrong" for r in mine]
        debatable = sum(r["changed"] and r["verdict"] == "debatable" for r in mine)
    else:
        hits = [r["verdict"] == "wrong" for r in mine]
        debatable = sum(r["verdict"] == "debatable" for r in mine)
    rest = [(r, hit) for r, hit in zip(mine, hits, strict=True) if not r["trap"]]
    rate, low, high = estimate([r for r, _ in rest], [hit for _, hit in rest])
    census = sum(s["traps"] for s in strata)
    kept = sum(s["kept"] for s in strata) - census
    base = sum(v2) + census
    return {
        "tier": tier,
        "no_kept_code_edits": kept + census,
        "no_unique_edits": sum(s["population"] for s in strata),
        "sampled": len(mine),
        "tests_written": sum(r["written"] == "test" for r in mine),
        "no_test": sum(r["written"] == "no_test" for r in mine),
        "fails_after": sum(r["changed"] for r in mine) if tier == "confirmed" else "",
        "wrong": sum(hits),
        "debatable": debatable,
        "wrong_share_of_sample": round(sum(hits) / len(mine), 4) if mine else "",
        "trap_census": census,
        "sampled_trap_removals": sum(r["trap"] for r in mine),
        "other_no_kept_code_edits": kept,
        "miss_rate_estimate": round(rate, 4),
        "miss_ci_low_estimate": round(low, 4),
        "miss_ci_high_estimate": round(high, 4),
        "v2_wrong_confirmed": v2[0],
        "v2_wrong_reading": v2[1],
        "missed_estimate": round(rate * kept, 1),
        "corrected_wrong_estimate": round(base + rate * kept, 1),
        "corrected_ci_low_estimate": round(base + low * kept, 1),
        "corrected_ci_high_estimate": round(base + high * kept, 1),
    }


def table_rows(sample: dict, results: dict, readings: dict, v2: dict, written: dict) -> list[dict]:
    """The table's rows, per tier: each method, then all four together."""
    weight = rest_weights(sample)
    mine = [
        {
            **e,
            "weight": weight[(e["method"], e["target_set"])],
            "written": written.get(e["edit"], ""),
            "changed": bool(results.get(e["edit"], {}).get("confirmed")),
            "verdict": readings.get(e["edit"], {}).get("verdict", ""),
        }
        for e in sample["edits"]
    ]
    methods = sorted({s["method"] for s in sample["strata"]})
    out = []
    for tier in TIERS:
        for method in [*methods, "overall"]:
            rows = [r for r in mine if method in ("overall", r["method"])]
            strata = [s for s in sample["strata"] if method in ("overall", s["method"])]
            counts = [v2.get(m, (0, 0)) for m in methods if method in ("overall", m)]
            base = (sum(c for c, _ in counts), sum(r for _, r in counts))
            out.append({"method": method, **tier_row(tier, rows, strata, base)})
    return out


def table() -> Path:
    sample_ = json.loads(SAMPLE.read_text())
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    readings = {}
    if READINGS.exists():
        for line in READINGS.read_text().splitlines():
            if line.strip():
                reading = json.loads(line)
                readings[reading["edit"]] = reading
    written = folders({e["edit"] for e in sample_["edits"]})
    rows = table_rows(sample_, results, readings, v2_wrong(), written)
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    with TABLE.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return TABLE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["sample", "run", "table"])
    parser.add_argument("--edits", nargs="*", help="run: only these edits (run again if done)")
    args = parser.parse_args(argv)
    if args.what == "sample":
        print(sample())
    elif args.what == "run":
        on_start()
        print(run(args.edits))
    else:
        print(table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
