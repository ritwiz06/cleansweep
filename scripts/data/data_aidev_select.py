"""Find runnable AIDev repositories: clone (blobless), install and test each in Docker.

    python scripts/data/data_aidev_select.py [--limit N]

Keeps repositories whose tests pass at least min_pass_rate (90%) and finish within
max_test_seconds (10 minutes). Stops after select_hours (3) or target_repos (40) kept.
Writes data/splits/aidev_repos.json (kept) and results/data_summary/aidev_filter.csv (every
candidate with its drop reason). Rerunning skips candidates already in the CSV.
Untrusted code runs only inside the containers.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cleansweep.core.config import load_config
from cleansweep.data.aidev import candidates
from cleansweep.data.swebench import data_path
from cleansweep.sandbox.aidev_docker import clone_dir, open_aidev

FIELDS = [
    "full_name",
    "stars",
    "merged_agent_prs",
    "status",
    "reason",
    "head_sha",
    "clone_url",
    "tests",
    "passed",
    "failed",
    "errors",
    "skipped",
    "pass_rate",
    "test_seconds",
    "install_seconds",
]
LOCK = threading.Lock()


# Git LFS files stay pointer files: our tools only parse code, and a global
# filter.lfs.required=true without git-lfs installed would make the checkout fail.
LFS_OFF = [
    "-c",
    "filter.lfs.required=false",
    "-c",
    "filter.lfs.smudge=",
    "-c",
    "filter.lfs.process=",
]


def clone(url: str, dest: Path, tries: int = 2) -> str | None:
    """A blobless clone at the default branch tip; returns its sha."""
    for attempt in range(tries):
        if not (dest / ".git").exists() or attempt:
            shutil.rmtree(dest, ignore_errors=True)
            dest.parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(
                ["git", *LFS_OFF, "clone", "-q", "--filter=blob:none", url, str(dest)],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if proc.returncode != 0:
                time.sleep(5)
                continue
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True)
        if out.stdout.strip():
            return out.stdout.strip()
    return None


def check(row: dict, cfg: dict) -> dict:
    """One candidate: clone, install, test. Returns the CSV row."""
    rec = {k: row.get(k, "") for k in FIELDS}
    rec.update(status="dropped")
    try:
        sha = clone(row["clone_url"], clone_dir(cfg, row["full_name"]))
    except subprocess.TimeoutExpired:
        sha = None
    if sha is None:
        return {**rec, "reason": "clone failed"}
    rec["head_sha"] = sha
    t0 = time.time()
    try:
        ws = open_aidev(
            f"aidev:{row['full_name']}@{sha}",
            {**cfg, "install_timeout_s": cfg["install_timeout_s"]},
        )
    except Exception as exc:
        reason = (
            "install failed"
            if "install failed" in str(exc)
            else f"open failed: {type(exc).__name__}"
        )
        return {**rec, "reason": reason, "install_seconds": round(time.time() - t0)}
    rec["install_seconds"] = round(time.time() - t0)
    try:
        result = ws.run_tests(None, timeout=int(cfg["max_test_seconds"]))
    finally:
        ws.close()
    total = result.passed + result.failed + result.errors
    rec.update(
        tests=total,
        passed=result.passed,
        failed=result.failed,
        errors=result.errors,
        skipped=result.skipped,
        pass_rate=round(result.passed / total, 3) if total else 0.0,
        test_seconds=round(result.duration_s),
    )
    if "<timeout>" in result.failed_ids:
        return {**rec, "reason": "tests over the time limit"}
    if total < int(cfg["min_tests"]):
        return {**rec, "reason": f"fewer than {cfg['min_tests']} tests ran"}
    if rec["pass_rate"] < float(cfg["min_pass_rate"]):
        return {**rec, "reason": f"pass rate below {cfg['min_pass_rate']:.0%}"}
    return {**rec, "status": "kept", "reason": ""}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="only the first N candidates (testing)")
    args = parser.parse_args(argv)
    cfg = {**load_config()["data"]["aidev"], **load_config()["core"]["sandbox"]}
    cfg["aidev_clones"] = cfg["clones"]
    out_csv = data_path("results/data_summary/aidev_filter.csv")
    out_json = data_path("data/splits/aidev_repos.json")
    done = list(csv.DictReader(out_csv.open())) if out_csv.exists() else []
    seen = {r["full_name"] for r in done}
    todo = [r for r in candidates(cfg).to_dict("records") if r["full_name"] not in seen]
    todo = todo[: args.limit] if args.limit else todo
    deadline = time.time() + float(cfg["select_hours"]) * 3600
    kept = sum(r["status"] == "kept" for r in done)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out_csv.exists()
    f = out_csv.open("a", newline="")
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    if new_file:
        writer.writeheader()

    def work(row: dict) -> None:
        nonlocal kept
        if time.time() > deadline or kept >= int(cfg["target_repos"]):
            rec = {
                **{k: row.get(k, "") for k in FIELDS},
                "status": "not checked",
                "reason": "selection stopped (time or enough repos)",
            }
        else:
            rec = check(row, cfg)
        with LOCK:
            kept += rec["status"] == "kept"
            writer.writerow(rec)
            f.flush()
            print(f"{rec['full_name']}: {rec['status']} {rec['reason']} ({kept} kept)", flush=True)

    with ThreadPoolExecutor(max_workers=int(cfg["workers"])) as pool:
        list(pool.map(work, todo))
    f.close()
    rows = list(csv.DictReader(out_csv.open()))
    keep = [r for r in rows if r["status"] == "kept"]
    for r in keep:
        for k in ("stars", "merged_agent_prs", "tests", "passed", "failed", "errors"):
            r[k] = int(r[k])
        r["pass_rate"], r["test_seconds"] = float(r["pass_rate"]), int(float(r["test_seconds"]))
    out_json.write_text(json.dumps(keep, indent=1) + "\n")
    print(f"{len(keep)} kept of {len(rows)} candidates -> {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
