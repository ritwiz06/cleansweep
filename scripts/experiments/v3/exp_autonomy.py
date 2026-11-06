"""Autonomy benchmark (v3): `cleansweep clean` on each AUTONOMY repository of
data/splits/v3_repos.json, as a user would run it: the agent team, safe mode, the Docker sandbox
on, no human help. A run completes when it ends with a report and one of the verdicts below,
with no traceback; anything else is a failure, sorted into a small taxonomy.

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
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = ROOT / "results" / "raw" / "autonomy"
SUMMARY = ROOT / "results" / "summary" / "v3"
SPLIT = ROOT / "data" / "splits" / "v3_repos.json"
CLONES = ROOT / "data" / "raw" / "aidev" / "repos"
VERDICTS = ("everything runs", "nothing applied", "not verified by tests", "stopped")
CAP_MINUTES = 75
BUDGET = "minutes=60"
FAILURES = [  # (class, text in stderr or stdout), first match wins
    ("docker", "docker"),
    ("install", "install failed"),
    ("llm", "LLMError"),
    ("timeout", "<cap>"),
    ("crash", "Traceback"),
]


def autonomy_repos(split: Path = SPLIT) -> dict[str, dict]:
    return {r["full_name"]: r for r in json.loads(split.read_text())["autonomy"]}


def export_tree(full_name: str, sha: str, dest: Path) -> None:
    """The repository's files at sha (no .git), as a plain folder."""
    clone = CLONES / full_name.replace("/", "__")
    dest.mkdir(parents=True)
    archive = subprocess.Popen(["git", "archive", sha], cwd=clone, stdout=subprocess.PIPE)
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


def verdict_of(stdout: str) -> str:
    """The verdict from clean's last "Result: <verdict>." line, or ""."""
    for line in reversed(stdout.splitlines()):
        if line.startswith("Result: "):
            return line.removeprefix("Result: ").split(".", 1)[0].strip()
    return ""


def classify(code: int | None, stdout: str, stderr: str, report: bool) -> tuple[bool, str]:
    """(completed, failure class): completed means a report, a known verdict, no traceback."""
    verdict = verdict_of(stdout)
    known = any(verdict.startswith(v) for v in VERDICTS)
    if code is not None and report and known and "Traceback" not in stderr:
        return True, ""
    text = stderr + stdout + ("<cap>" if code is None else "")
    for name, needle in FAILURES:
        if needle in text:
            return False, name
    return False, "no report" if not report else "unknown verdict"


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
        for name in ("report.json", "CLEANUP_REPORT.md", "events.jsonl"):
            found = sorted(out.glob(f"**/{name}")) if out.exists() else []
            if found:
                shutil.copy(found[0], folder / name)
        completed, failure = classify(code, stdout, stderr, bool(reports))
        result = {
            "repo": full_name,
            "pass": k,
            "traits": entry.get("traits", []),
            "exit_code": code,
            "verdict": verdict_of(stdout),
            "completed": completed,
            "failure": failure,
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
        low, high = wilson(done, len(mine))
        verdicts = Counter(r["verdict"] or "-" for r in mine if str(r["completed"]) == "True")
        failures = Counter(r["failure"] for r in mine if str(r["completed"]) != "True")
        out.append(
            {
                "pass": k,
                "runs": len(mine),
                "completed": done,
                "rate": round(done / len(mine), 3) if mine else "",
                "ci_low": low,
                "ci_high": high,
                "verdicts": "; ".join(f"{v}: {n}" for v, n in sorted(verdicts.items())),
                "failures": "; ".join(f"{f}: {n}" for f, n in sorted(failures.items())),
            }
        )
    return out


def table() -> tuple[Path, Path]:
    rows = [json.loads(p.read_text()) for p in sorted(RAW.glob("*/pass*/result.json"))]
    for r in rows:
        r["traits"] = " ".join(r["traits"])
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
        print(json.dumps(run_one(full_name, repos[full_name], args.k)), flush=True)
    print(*table(), sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
