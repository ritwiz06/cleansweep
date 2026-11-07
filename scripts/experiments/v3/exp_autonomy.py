"""Autonomy benchmark (v3): `cleansweep clean` on each AUTONOMY repository of
data/splits/v3_repos.json, as a user would run it: the agent team, safe mode, the Docker sandbox
on, no human help. Every run should end with a report and one of clean's verdicts (agents/
reporter.py VERDICTS). A run completes when its verdict is a cleanup outcome (everything runs,
nothing applied, not verified by tests, not verified); a "stopped: <reason>" verdict is valid but
not completed, and its reason is classified; no report, an unknown verdict, a traceback on the
terminal or the time cap are failures too. A run that did not complete is also put in one of the
environment-impossible categories fixed in docs/preregistration_v3.md when its evidence says so:
it needs a GPU, needs the network after the install, needs a native toolchain or a service the
image lacks, or is not a Python project. The table reports the raw completion rate (R19 is judged
on it) and the rate without those runs.

    python scripts/experiments/v3/exp_autonomy.py run [--repos owner/name ...] [--pass 1|2]
    python scripts/experiments/v3/exp_autonomy.py table

run: copies each repository's tree at its screened head into a scratch folder (a plain folder,
so not a repository the user owns), runs `python -m cleansweep.cli clean` on it in a subprocess
with a time cap, and keeps stdout, stderr and the run's report in
results/raw/autonomy/<name>/pass<k>/. Pass 2 reruns only the repositories pass 1 failed, after
the fixes (v2.1.1). Resumable: a repository with a result.json for the pass is skipped.
table: results/summary/v3/autonomy_runs.csv (one row per repository and pass) and
autonomy.csv (per pass: runs, completed, the completion rate with a Wilson interval, the verdict
mix and the failure taxonomy).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = ROOT / "results" / "raw" / "autonomy"
SUMMARY = ROOT / "results" / "summary" / "v3"
SPLIT = ROOT / "data" / "splits" / "v3_repos.json"
CLONES = ROOT / "data" / "raw" / "aidev" / "repos"
OUTCOMES = ("everything runs", "nothing applied", "not verified by tests", "not verified")
CAP_MINUTES = 75
BUDGET = "minutes=60"
FAILURES = [  # (class, text in the stop reason, stderr or stdout), first match wins
    ("timeout", "<cap>"),
    ("docker", "docker"),
    ("install", "install"),
    ("llm", "llm"),
    ("budget", "budget"),
    ("interrupted", "interrupt"),
    ("crash", "traceback"),
]


# (category, evidence pattern in the verdict, the terminal and error.log), first match wins
ENVIRONMENT = [
    ("needs a GPU", r"cuda|cudnn|nvidia|nccl|no gpu|gpu is required"),
    (
        "needs the network after install",
        r"name resolution|name or service not known|network is unreachable|"
        r"nodename nor servname|max retries exceeded with url|connectionerror",
    ),
    (
        "needs a native toolchain or a service",
        r"\bgcc\b|\bg\+\+|\bclang\b|cmake|pkg-config|rustc|cargo build|libpq|postgres|"
        r"mysql|redis|mongo|elasticsearch|docker daemon|xvfb|cannot open display",
    ),
]


def environment(verdict: str, stdout: str, stderr: str, py_files: int) -> str:
    """The environment-impossible category a run's evidence shows, or ""."""
    if py_files == 0:
        return "not a Python project"
    text = f"{verdict}\n{stdout}\n{stderr}".lower()
    for name, pattern in ENVIRONMENT:
        if re.search(pattern, text):
            return name
    return ""


def autonomy_repos(split: Path = SPLIT) -> dict[str, dict]:
    return {r["full_name"]: r for r in json.loads(split.read_text())["autonomy"]}


# Git LFS files stay pointer files (as data_aidev_select.py clones them): a filter.lfs.process
# set globally without git-lfs installed would make the archive fail.
LFS_OFF = [
    "-c",
    "filter.lfs.required=false",
    "-c",
    "filter.lfs.smudge=",
    "-c",
    "filter.lfs.process=",
]


def export_tree(full_name: str, sha: str, dest: Path) -> None:
    """The repository's files at sha (no .git), as a plain folder."""
    clone = CLONES / full_name.replace("/", "__")
    dest.mkdir(parents=True)
    archive = subprocess.Popen(["git", *LFS_OFF, "archive", sha], cwd=clone, stdout=subprocess.PIPE)
    subprocess.run(["tar", "-xf", "-", "-C", str(dest)], stdin=archive.stdout, check=True)
    if archive.wait() != 0:
        raise RuntimeError(f"git archive failed for {full_name}@{sha}")


def clean_command(project: Path, out: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "cleansweep.cli",
        "clean",
        str(project),
        "--mode",
        "safe",
        "--sandbox",
        "docker",
        "--budget",
        BUDGET,
        "--out",
        str(out),
        "--quiet",
    ]


def verdict_of(stdout: str, report: dict | None = None) -> str:
    """The run's verdict: from its report.json when there is one, else clean's "Result:" line."""
    if report:
        verdict = report.get("stats", {}).get("agentic", {}).get("verdict")
        if verdict:
            return verdict
    for line in reversed(stdout.splitlines()):
        if line.startswith("Result: "):
            return line.removeprefix("Result: ").rsplit(". ", 1)[0].rstrip(".")
    return ""


def classify(code: int | None, verdict: str, stdout: str, stderr: str) -> tuple[bool, bool, str]:
    """(valid verdict, completed, failure class)."""
    stopped = verdict.startswith("stopped:")
    valid = code is not None and (verdict in OUTCOMES or stopped) and "Traceback" not in stderr
    if valid and not stopped:
        return True, True, ""
    text = (verdict + "\n" + stderr + stdout + ("<cap>" if code is None else "")).lower()
    for name, needle in FAILURES:
        if needle in text:
            return valid, False, name
    if stopped:
        return valid, False, "other stop"
    return valid, False, "no verdict" if not verdict else "unknown verdict"


def run_one(full_name: str, entry: dict, k: int) -> dict:
    folder = RAW / full_name.replace("/", "__") / f"pass{k}"
    folder.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="cs_autonomy_"))
    project, out = work / full_name.split("/")[1], work / "out"
    t0 = time.time()
    try:
        export_tree(full_name, entry["head_sha"], project)
        try:
            proc = subprocess.run(
                clean_command(project, out),
                capture_output=True,
                text=True,
                timeout=CAP_MINUTES * 60,
                cwd=ROOT,
            )
            code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            code = None
            stdout = (exc.stdout or b"").decode(errors="replace")
            stderr = (exc.stderr or b"").decode(errors="replace")
        (folder / "stdout.txt").write_text(stdout)
        (folder / "stderr.txt").write_text(stderr)
        reports = sorted(out.glob("**/report.json")) if out.exists() else []
        for name in ("report.json", "CLEANUP_REPORT.md", "events.jsonl", "error.log"):
            found = sorted(out.glob(f"**/{name}")) if out.exists() else []
            if found:
                shutil.copy(found[0], folder / name)
        report = json.loads(reports[0].read_text()) if reports else None
        verdict = verdict_of(stdout, report)
        valid, completed, failure = classify(code, verdict, stdout, stderr)
        # the evidence: the verdict, the terminal and error.log, never the report's code excerpts
        error_log = (
            (folder / "error.log").read_text(errors="replace")
            if (folder / "error.log").exists()
            else ""
        )
        py_files = sum(1 for _ in project.rglob("*.py"))
        env = "" if completed else environment(verdict, stdout + error_log, stderr, py_files)
        result = {
            "repo": full_name,
            "pass": k,
            "traits": entry.get("traits", []),
            "exit_code": code,
            "verdict": verdict,
            "valid_verdict": valid,
            "completed": completed,
            "failure": failure,
            "environment": env,
            "minutes": round((time.time() - t0) / 60, 2),
        }
        (folder / "result.json").write_text(json.dumps(result, indent=1))
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(centre - half, 3), round(centre + half, 3)


def summarize(rows: list[dict]) -> list[dict]:
    out = []
    for k in sorted({int(r["pass"]) for r in rows}):
        mine = [r for r in rows if int(r["pass"]) == k]
        done = sum(str(r["completed"]) == "True" for r in mine)
        valid = sum(str(r.get("valid_verdict")) == "True" for r in mine)
        possible = [r for r in mine if not r.get("environment")]
        adj_low, adj_high = wilson(done, len(possible))
        low, high = wilson(done, len(mine))
        verdicts = Counter(r["verdict"] or "-" for r in mine if str(r["completed"]) == "True")
        failures = Counter(r["failure"] for r in mine if str(r["completed"]) != "True")
        out.append(
            {
                "pass": k,
                "runs": len(mine),
                "valid_verdict": valid,
                "completed": done,
                "rate": round(done / len(mine), 3) if mine else "",
                "ci_low": low,
                "ci_high": high,
                "environment_impossible": len(mine) - len(possible),
                "rate_without_them": round(done / len(possible), 3) if possible else "",
                "adjusted_ci_low": adj_low,
                "adjusted_ci_high": adj_high,
                "verdicts": "; ".join(f"{v}: {n}" for v, n in sorted(verdicts.items())),
                "failures": "; ".join(f"{f}: {n}" for f, n in sorted(failures.items())),
            }
        )
    return out


def no_paths(text: str) -> str:
    """The text with quoted absolute paths (the run's scratch folders) replaced by <path>."""
    return re.sub(r"(['\"])/[^'\"]*\1", r"\1<path>\1", text)


def table() -> tuple[Path, Path]:
    rows = [json.loads(p.read_text()) for p in sorted(RAW.glob("*/pass*/result.json"))]
    for r in rows:
        r["traits"] = " ".join(r["traits"])
        r["verdict"] = no_paths(r["verdict"] or "")
    SUMMARY.mkdir(parents=True, exist_ok=True)
    runs, summary = SUMMARY / "autonomy_runs.csv", SUMMARY / "autonomy.csv"
    for path, data in ((runs, rows), (summary, summarize(rows))):
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    return runs, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["run", "table"])
    parser.add_argument("--repos", nargs="+")
    parser.add_argument("--pass", dest="k", type=int, default=1, choices=[1, 2])
    args = parser.parse_args(argv)
    if args.what == "table":
        print(*table(), sep="\n")
        return 0
    repos = autonomy_repos()
    for full_name in args.repos or list(repos):
        folder = RAW / full_name.replace("/", "__")
        if (folder / f"pass{args.k}" / "result.json").exists():
            continue
        if args.k == 2:
            first = folder / "pass1" / "result.json"
            if not first.exists() or json.loads(first.read_text())["completed"]:
                continue
        try:
            print(json.dumps(run_one(full_name, repos[full_name], args.k)), flush=True)
        except Exception as exc:  # a harness error, not a run's outcome: logged, retried later
            (folder / f"error_pass{args.k}.txt").parent.mkdir(parents=True, exist_ok=True)
            (folder / f"error_pass{args.k}.txt").write_text(traceback.format_exc())
            print(f"error {full_name}: {type(exc).__name__}: {exc}", flush=True)
    print(*table(), sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
