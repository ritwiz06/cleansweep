"""The audit-miss estimate repeated on the v3 runs' own edits (docs/preregistration_v3.md):
exp_audit_miss.py's design on the kept code edits of the finished v3 runs, run 1, of the team
and v1, once they are audited.

    python scripts/experiments/v3/exp_audit_miss_v3.py sample [--raw DIR ...]
    python scripts/experiments/v3/exp_audit_miss_v3.py run [--edits ID ...] [--raw DIR ...]
    python scripts/experiments/v3/exp_audit_miss_v3.py table [--raw DIR ...]

sample: 50 "no"-voted kept code edits each for the team (agentic) and v1 (cleansweep), seed 572,
drawn as exp_audit_miss.py draws (proportional to the sets, injected v3 and real v3; each edit
weighted by its cell's population over its sampled edits). The population leaves out edits the
v3 audit already settled (a check from a rule, a targeted test or a reading: the injection key's
rule settles every kept INJECT edit that removes a plant or a trap) and the runs that timed out,
as audit.csv does. Writes results/raw/audit_miss_v3/sample.json.
run: as exp_audit_miss.py, with tests in results/raw/audit_miss_v3/tests/<edit>/ (hide.txt for a
dependency removal, no_test.txt when no test can be written), each project opened from the clone
its run used (exp_audit_confirm_v3.py).
table: results/summary/v3/audit_miss_v3.csv, exp_audit_miss.py's columns, with the v3 audit's
wrong edits of the same finished runs (audit_wrong_confirmed, audit_wrong_reading) in place of
v2's; readings in results/raw/audit_miss_v3/readings.jsonl. Every rate and corrected count is an
estimate.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import exp_audit_confirm_v3  # noqa: E402
import exp_tables_v3  # noqa: E402

ROOT = HERE.parents[2]
RAW = ROOT / "results" / "raw" / "audit_miss_v3"
TABLE = ROOT / "results" / "summary" / "v3" / "audit_miss_v3.csv"
PER_METHOD = 50
METHODS = {"agentic": "agentic", "cleansweep": "cleansweep"}
TARGET_SETS = {"injected v3": "injected v3", "real v3": "real v3"}
RENAMED = {"v2_wrong_confirmed": "audit_wrong_confirmed", "v2_wrong_reading": "audit_wrong_reading"}


def load(raws: list[Path]):
    """exp_audit_miss.py, reading the v3 audit and runs and writing the v3 audit-miss files."""
    confirm = exp_audit_confirm_v3.load(raws)
    sys.modules["exp_audit_confirm"] = confirm
    path = HERE / "exp_audit_miss.py"
    spec = importlib.util.spec_from_file_location("exp_audit_miss_v3_base", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.RAW, module.TESTS = RAW, RAW / "tests"
    module.SAMPLE, module.RESULTS = RAW / "sample.json", RAW / "results.json"
    module.READINGS, module.TABLE = RAW / "readings.jsonl", TABLE
    module.PER_METHOD, module.METHODS, module.TARGET_SETS = PER_METHOD, METHODS, TARGET_SETS
    return module


def finished(raws: list[Path]) -> dict[str, set]:
    """The audit's run ids of the finished runs of run 1, per "set|method"."""
    inject, real = exp_tables_v3.inject_records(raws), exp_tables_v3.real_records(raws)
    return exp_tables_v3.finished_runs(inject, real)


def counted(row: dict, done: dict[str, set]) -> bool:
    """An occurrence in a finished run of the team or v1."""
    runs = done.get(f"{row['source']}|{row['method']}", set())
    return row["method"] in METHODS and row["run"] in runs


def population(rows: list[dict], audit: dict, checks: dict, done: dict[str, set]) -> dict:
    """(method, set) -> {unsettled "no"-voted edit: how many of the method's kept code edits it
    is}, over the finished runs."""
    out: dict[tuple[str, str], dict[str, int]] = {}
    for r in rows:
        if not counted(r, done):
            continue
        if audit.get(r["edit"], {}).get("answer") != "no" or r["edit"] in checks:
            continue
        cell = out.setdefault((METHODS[r["method"]], TARGET_SETS[r["source"]]), {})
        cell[r["edit"]] = cell.get(r["edit"], 0) + 1
    return out


def audit_wrong(rows: list[dict], checks: dict, done: dict, confirmed: set) -> dict:
    """method -> (wrong kept code edits confirmed, by reading) in the v3 audit's finished runs."""
    out: dict[str, tuple[int, int]] = {}
    for r in rows:
        if not counted(r, done):
            continue
        check = checks.get(r["edit"])
        if check and check["verdict"] == "wrong":
            c, rd = out.get(r["method"], (0, 0))
            hit = check.get("checked_by") in confirmed
            out[r["method"]] = (c + hit, rd + (not hit))
    return out


def sample(miss, raws: list[Path]) -> Path:
    audit_module = sys.modules["exp_diff_audit"]
    edits, rows = miss.collect()
    audit = json.loads((miss.AUDIT / "audit.json").read_text())
    pop = population(rows, audit, audit_module.checks(), finished(raws))
    out = miss.draw(pop, edits)
    for method in sorted(METHODS.values()):
        n = sum(s["sampled"] for s in out["strata"] if s["method"] == method)
        if n < PER_METHOD:
            print(f"{method}: only {n} unsettled no-voted edits, all taken")
    RAW.mkdir(parents=True, exist_ok=True)
    miss.SAMPLE.write_text(json.dumps(out, indent=1))
    return miss.SAMPLE


def table(miss, raws: list[Path]) -> Path:
    audit_module = sys.modules["exp_diff_audit"]
    _, rows = miss.collect()
    base = audit_wrong(rows, audit_module.checks(), finished(raws), audit_module.CONFIRMED)
    sample_ = json.loads(miss.SAMPLE.read_text())
    results = json.loads(miss.RESULTS.read_text()) if miss.RESULTS.exists() else {}
    readings = {}
    if miss.READINGS.exists():
        for line in miss.READINGS.read_text().splitlines():
            if line.strip():
                reading = json.loads(line)
                readings[reading["edit"]] = reading
    written = miss.folders({e["edit"] for e in sample_["edits"]})
    out = [
        {RENAMED.get(k, k): v for k, v in row.items()}
        for row in miss.table_rows(sample_, results, readings, base, written)
    ]
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    with TABLE.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    return TABLE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["sample", "run", "table"])
    parser.add_argument("--edits", nargs="*", help="run: only these edits (run again if done)")
    parser.add_argument("--raw", type=Path, action="append", help="a results/raw folder")
    args = parser.parse_args(argv)
    raws = args.raw or [ROOT / "results" / "raw"]
    miss = load(raws)
    if args.what == "sample":
        print(sample(miss, raws))
    elif args.what == "run":
        miss.on_start()
        print(miss.run(args.edits))
    else:
        print(table(miss, raws))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
