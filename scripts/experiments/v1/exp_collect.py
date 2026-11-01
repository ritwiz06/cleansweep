"""Merge the toy, demo, SWE-bench Tier 1 and Tier 2 and AIDev runs into
results/summary/v1/main_results.csv.

    python scripts/experiments/v1/exp_collect.py [--t2 FOLDER] [--t2-oneshot FOLDER]
        [--t2-rerun FOLDER] [--aidev FOLDER] [--aidev-rerun FOLDER ...] [--oneshot-retry FOLDER]

The run folders default to the run copies' raw reports in ../cleansweep-archive
(scripts/experiments/v1/archive_paths.py); a default that is missing stops the script with the
flag to pass.

One row per (target, method). Toy and demo rows come from the recorded live runs listed in
LOCAL_RUNS (2026-10-26 on); SWE-bench rows from the runners' report files. Tier 2 one-shot rows
come from the rerun folder when it exists, and runs that failed in the first Tier 2 run are
filled in from the rerun folder. hidden_flaky marks a hidden change that another method's
identical edits on the same target did not repeat. An AIDev run without second-model hidden
tests, or whose diff did not apply in the hidden-check workspace, has no hidden outcome (empty,
not 0). AIDev runs that failed in the grid are filled in from the rerun folders, and a repo
counts only once every method's run is in. Every AIDev report must record the scope it used
(stats["scope"]; data_aidev_scope.py --backfill adds it to older reports), or the run stops; a
report whose agent scope was missing (the sweep saw the whole repository) is listed and left out,
so a rerun folder's scoped run fills in.

Format and unused-import edits are counted on their own, and lines_removed_code is the net lines
the other applied edits remove (from each edit's own diff): reformatting can add more lines than
it removes and so hide deleted code in lines_removed. test_slowdown is an AIDev run's first test
run against the repo's selection-time test time (data/splits/aidev_repos.json);
overload_suspect marks a run where it more than doubled.

Two stronger one-shot variants are derived from the one_shot_llm rows. one_shot_compile discards
a diff whose rewritten files don't compile (results/summary/v1/oneshot_compile.csv, from
exp_oneshot_compile.py): no edits and nothing changed. one_shot_retry is the rerun with one
compile-error follow-up for those runs (--oneshot-retry, one report per SWE-bench patch, used for
Tier 1 and Tier 2) and the same as one_shot_llm elsewhere, since its first request is the same.
A run missing from either source gets no row.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_paths import archived, check_defaults  # noqa: E402

from app.live_runner import fold, read_events  # noqa: E402
from app.loaders import outcome_score  # noqa: E402
from cleansweep.core.io import load_json  # noqa: E402
from cleansweep.core.models import SweepReport  # noqa: E402

RAW = ROOT / "results" / "raw"
OUT = ROOT / "results" / "summary" / "v1" / "main_results.csv"
AIDEV_SPLIT = ROOT / "data" / "splits" / "aidev_repos.json"
COMPILE_CSV = ROOT / "results" / "summary" / "v1" / "oneshot_compile.csv"
LOCAL_RUNS = {
    "toy": "tests/fixtures/toy_repo",
    "demo": ".cleansweep/demo/shop_app",
}
FIELDS = [
    "target_set",
    "target",
    "method",
    "edits_applied",
    "lines_removed",
    "files_removed",
    "test_runs",
    "hidden_changed",
    "llm_calls",
    "minutes",
    "outcome_hits",
    "outcome_total",
    "invalid_output",
    "hidden_flaky",
    "format_edits",
    "import_edits",
    "lines_removed_code",
    "test_slowdown",
    "overload_suspect",
]
OUTCOMES = (
    "edits_applied",
    "lines_removed",
    "files_removed",
    "hidden_changed",
    "format_edits",
    "import_edits",
    "lines_removed_code",
)
SEPARATE = {"format": "format_edits", "unused_import": "import_edits"}
# changed lines, not the "--- a/x" / "+++ b/x" file headers
MINUS = re.compile(r"^-(?!-- (?:a/|/dev/null))", re.MULTILINE)
PLUS = re.compile(r"^\+(?!\+\+ (?:b/|/dev/null))", re.MULTILINE)
OVERLOAD = 2.0


def _digest(diff: str) -> str:
    return hashlib.sha256(diff.encode()).hexdigest()[:16]


def mark_flaky(rows: list[dict]) -> list[dict]:
    """A hidden change is flaky when another method made the same edits (same final diff) on
    the same target and its hidden checks did not change: the test, not the edit, flipped."""
    unchanged = {
        (r["target_set"], r["_group"], r["_diff"]) for r in rows if r["hidden_changed"] == 0
    }
    out = []
    for r in rows:
        key = (r["target_set"], r["_group"], r["_diff"])
        flaky = int(r["hidden_changed"] == 1 and key in unchanged)
        out.append({k: v for k, v in r.items() if not k.startswith("_")} | {"hidden_flaky": flaky})
    return out


def _invalid(row: dict, stats: dict) -> dict:
    """A one-shot reply that didn't parse is not "0 edits": its outcomes are left empty."""
    bad = int(stats.get("invalid_output", 0))
    return {**row, **dict.fromkeys(OUTCOMES, "")} | {"invalid_output": bad} if bad else row


def label(method: str, judge_mode: str | None) -> str:
    return f"cleansweep-{judge_mode}" if method == "cleansweep" else method


def _applied(results) -> int:
    get = (lambda r, k: r[k]) if results and isinstance(results[0], dict) else getattr
    return sum(
        get(r, "status") in ("kept", "repaired") and bool(get(r, "diff").strip()) for r in results
    )


def edit_counts(data: dict) -> dict:
    """Applied format and unused-import edits, and the net lines the other applied edits remove."""
    category = {i["item_id"]: i["category"] for i in data["plan"]["items"]}
    out = dict.fromkeys(SEPARATE.values(), 0)
    net = 0
    for r in data["results"]:
        if r["status"] not in ("kept", "repaired") or not (r.get("diff") or "").strip():
            continue
        key = SEPARATE.get(category.get(r["item_id"], ""))
        if key:
            out[key] += 1
        else:
            net += len(MINUS.findall(r["diff"])) - len(PLUS.findall(r["diff"]))
    return {**out, "lines_removed_code": max(net, 0)}


def slowdown(data: dict, baseline: float | None) -> dict:
    """The run's first test run against the repo's first baseline; empty without either."""
    first = next((r["tests"]["duration_s"] for r in data["results"] if r.get("tests")), None)
    if not first or not baseline:
        return {"test_slowdown": "", "overload_suspect": ""}
    ratio = first / baseline
    return {"test_slowdown": round(ratio, 2), "overload_suspect": int(ratio > OVERLOAD)}


def local_rows() -> list[dict]:
    rows = []
    for run_dir in sorted((RAW / "live").glob("2026102[6-9]_*")):
        if not (run_dir / "report.json").exists():
            continue
        state = fold(read_events(run_dir / "events.jsonl"))
        run = state["run"]
        target_set = next(
            (k for k, v in LOCAL_RUNS.items() if run["target"].rstrip("/") == v), None
        )
        if target_set is None:
            continue
        report = load_json(SweepReport, run_dir / "report.json")
        key = ROOT / (LOCAL_RUNS[target_set] + "_expected.json")
        score = outcome_score(report, key) if key.exists() else None
        stats = report.stats
        row = {
            "target_set": target_set,
            "target": run_dir.name,
            "method": label(run["method"], run.get("judge_mode")),
            "edits_applied": _applied(report.results),
            "lines_removed": stats["lines_removed"],
            "files_removed": stats["files_removed"],
            "test_runs": stats["test_runs"],
            "hidden_changed": int(bool((state["hidden"] or {}).get("behavior_changed"))),
            "llm_calls": stats["llm_calls"],
            "minutes": round(stats["wall_seconds"] / 60, 2),
            "outcome_hits": score["hits"] if score else "",
            "outcome_total": score["total"] if score else "",
            "invalid_output": 0,
            "_group": target_set,
            "_diff": _digest(stats.get("final_diff", "")),
        }
        rows.append(_invalid(row, stats))
    return rows


def swebench_rows(
    folder: Path, target_set: str, baselines: dict[str, float] | None = None
) -> list[dict]:
    """One row per report <a>__<b>__<method>.json: SWE-bench <instance>__<agent>, or AIDev
    <owner>__<name> (with `baselines`: the repo's selection-time test seconds by target)."""
    rows = []
    for path in sorted(folder.glob("*__*__*.json")):
        instance, agent, method = path.stem.rsplit("__", 2)
        data = json.loads(path.read_text())
        stats = data["stats"]
        hidden = stats.get("hidden") or {}
        row = {
            "target_set": target_set,
            "target": f"{instance}__{agent}",
            "method": method,
            "edits_applied": _applied(data["results"]),
            "lines_removed": stats["lines_removed"],
            "files_removed": stats["files_removed"],
            "test_runs": stats["test_runs"],
            "hidden_changed": int(bool(hidden.get("behavior_changed")))
            if hidden.get("available", True) and hidden.get("applied") is not False
            else "",
            "llm_calls": stats["llm_calls"],
            "minutes": stats["minutes"],
            "outcome_hits": "",
            "outcome_total": "",
            "invalid_output": 0,
            **edit_counts(data),
            **(slowdown(data, baselines.get(f"{instance}__{agent}")) if baselines else {}),
            "_group": f"{instance}__{agent}",
            "_diff": _digest(stats.get("final_diff", "")),
            "_scope": _scope_kind(stats.get("scope") or {}),
        }
        rows.append(_invalid(row, stats))
    return rows


def _scope_kind(record: dict) -> str | None:
    """The scope kind of a complete record: an agent scope also needs its units and share."""
    kind = record.get("kind")
    if kind in ("agent_patch", "agent_blame") and not {"units", "share"} <= set(record):
        return None
    return kind


def scoped(rows: list[dict], folder: Path) -> list[dict]:
    """AIDev rows whose report used the agent scope. A report without a complete scope record
    (kind; units and share for an agent scope) stops the run; one whose scope was missing is
    listed and left out."""
    lacking = sorted(f"{r['target']}__{r['method']}" for r in rows if not r["_scope"])
    if lacking:
        raise SystemExit(
            f"{len(lacking)} AIDev reports in {folder} have no complete scope record "
            f"(run data_aidev_scope.py --backfill {folder}): {', '.join(lacking[:3])}"
        )
    missing = sorted(f"{r['target']}__{r['method']}" for r in rows if r["_scope"] == "missing")
    if missing:
        print(
            f"left out, agent scope missing: {len(missing)} reports in {folder.parent.name}/"
            f"{folder.name} ({', '.join(sorted({m.rsplit('__', 1)[0] for m in missing}))})"
        )
    return [r for r in rows if r["_scope"] != "missing"]


def aidev_baselines() -> dict[str, float]:
    """Selection-time test seconds per AIDev target (<owner>__<name>)."""
    if not AIDEV_SPLIT.exists():
        return {}
    repos = json.loads(AIDEV_SPLIT.read_text(encoding="utf-8"))
    return {r["full_name"].replace("/", "__"): float(r["test_seconds"]) for r in repos}


def aidev_rows(folder: Path, reruns: list[Path], exclude: list[str]) -> list[dict]:
    """AIDev rows from the grid folder; runs missing there come from the rerun folders. A repo
    counts only once it has a run for every method (a rerun can still be going)."""
    baselines = aidev_baselines()
    rows = scoped(swebench_rows(folder, "aidev", baselines), folder) if folder.exists() else []
    for extra in (f for f in reruns if f.exists()):
        have = {(r["target"], r["method"]) for r in rows}
        rows += [
            r
            for r in scoped(swebench_rows(extra, "aidev", baselines), extra)
            if (r["target"], r["method"]) not in have
        ]
    rows = [r for r in rows if r["target"] not in exclude]
    runs = Counter(r["target"] for r in rows)
    return [r for r in rows if runs[r["target"]] == max(runs.values())]


def compile_status(path: Path = COMPILE_CSV) -> dict[tuple[str, str], bool]:
    """(target_set, target) -> whether the one-shot diff fails the compile check."""
    if not path.exists():
        return {}
    with path.open() as f:
        return {
            (r["target_set"], r["target"]): r["compile_failed"] == "1" for r in csv.DictReader(f)
        }


def oneshot_variants(
    rows: list[dict], failed: dict[tuple[str, str], bool], retries: dict[str, dict]
) -> list[dict]:
    """one_shot_compile and one_shot_retry rows from the one_shot_llm rows (see the module doc).
    A target set gets no one_shot_retry rows until every run there that failed to compile has its
    rerun: the others alone would be a biased sample."""
    nothing = dict.fromkeys(OUTCOMES, 0)
    out, waiting = [], set()
    for r in rows:
        if r["method"] != "one_shot_llm" or (r["target_set"], r["target"]) not in failed:
            continue
        if not failed[(r["target_set"], r["target"])]:
            out += [{**r, "method": "one_shot_compile"}, {**r, "method": "one_shot_retry"}]
            continue
        out.append({**r, **nothing, "method": "one_shot_compile", "_diff": _digest("")})
        if r["target"] in retries:
            out.append({**retries[r["target"]], "target_set": r["target_set"]})
        else:
            waiting.add(r["target_set"])
    return [r for r in out if not (r["method"] == "one_shot_retry" and r["target_set"] in waiting)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--t1", default=str(RAW / "swebench_t1"))
    parser.add_argument("--t2", default=str(archived("cleansweep-runs", "swebench_t2")))
    parser.add_argument(
        "--t2-oneshot",
        default=str(archived("cleansweep-runs-2", "swebench_t2_oneshot")),
        help="one_shot_llm reruns on Tier 2; preferred over the first run's one_shot_llm rows",
    )
    parser.add_argument(
        "--t2-rerun",
        default=str(archived("cleansweep-runs-2", "swebench_t2_rerun")),
        help="Tier 2 runs that failed in the first run (fixed code); fill in missing rows only",
    )
    parser.add_argument(
        "--aidev",
        default=str(archived("cleansweep-runs-3", "aidev_sweeps")),
        help="AIDev sweeps (exp_swebench.py on data/splits/aidev_repos.json)",
    )
    parser.add_argument(
        "--aidev-rerun",
        nargs="*",
        default=[
            str(archived("cleansweep-runs-5", "aidev_scoped")),
            str(archived("cleansweep-runs-8", "aidev_window")),
        ],
        help="AIDev runs missing from the grid, rerun with the agent scope; fill in missing rows",
    )
    parser.add_argument(
        "--aidev-exclude",
        nargs="*",
        default=[],
        help="AIDev repos to leave out (reports without an agent scope are left out anyway)",
    )
    parser.add_argument(
        "--oneshot-retry",
        default=str(archived("cleansweep-runs-6", "oneshot_retry")),
        help="one_shot_retry runs on the SWE-bench patches whose one-shot reply didn't compile",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=["psf__requests-2317"],
        help="SWE-bench instances left out (requests' tests need live network; DECISIONS)",
    )
    args = parser.parse_args(argv)
    flags = ["--t2", "--t2-oneshot", "--t2-rerun", "--aidev", "--aidev-rerun", "--oneshot-retry"]
    check_defaults("exp_collect.py", parser, args, flags)
    rows = local_rows() + swebench_rows(Path(args.t1), "swebench_t1")
    t2 = swebench_rows(Path(args.t2), "swebench_t2") if Path(args.t2).exists() else []
    if Path(args.t2_oneshot).exists():
        rerun = [r for r in swebench_rows(Path(args.t2_oneshot), "swebench_t2")]
        redone = {r["target"] for r in rerun if r["method"] == "one_shot_llm"}
        t2 = [r for r in t2 if not (r["method"] == "one_shot_llm" and r["target"] in redone)]
        t2 += [r for r in rerun if r["method"] == "one_shot_llm"]
    if Path(args.t2_rerun).exists():
        have = {(r["target"], r["method"]) for r in t2}
        extra = swebench_rows(Path(args.t2_rerun), "swebench_t2")
        t2 += [r for r in extra if (r["target"], r["method"]) not in have]
    t2 = [r for r in t2 if not any(r["target"].startswith(x + "__") for x in args.exclude)]
    aidev = aidev_rows(Path(args.aidev), [Path(f) for f in args.aidev_rerun], args.aidev_exclude)
    retry_dir = Path(args.oneshot_retry)
    retries = {r["target"]: r for r in swebench_rows(retry_dir, "")} if retry_dir.exists() else {}
    base = rows + t2 + aidev
    variants = oneshot_variants(base, compile_status(), retries)
    one_shot = sum(r["method"] == "one_shot_llm" for r in base)
    for method in ("one_shot_compile", "one_shot_retry"):
        n = sum(r["method"] == method for r in variants)
        if n < one_shot:
            print(f"{method}: {n} of {one_shot} one-shot runs (missing compile status or rerun)")
    rows = mark_flaky(base + variants)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["target_set"]] = counts.get(r["target_set"], 0) + 1
    print(f"{OUT.relative_to(ROOT)}: {len(rows)} rows {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
