"""Real-project evaluation (v3) with held-out real tests, on the REAL repositories of
data/splits/v3_repos.json. Each method cleans each project in its network-less container (safe
mode, the whole project in scope, at most 120 minutes) and sees only half of the project's own
test modules; the other half, held out by a fixed seed, is the hidden check.

    python scripts/experiments/v3/exp_real_v3.py prepare [--repos owner/name ...]
    python scripts/experiments/v3/exp_real_v3.py run [--repos ...] [--methods ...] [--run 1|2]

prepare: a held-out clone per repository (data/raw/aidev/heldout/<owner>__<name>): commit
"base" is the screened head; commit "visible" deletes the held-out test modules (test_*.py and
*_test.py, half of them, seeded; conftest.py and helpers stay). The held-out modules run on the
base commit in a container to record which pass before any cleanup. Writes
results/raw/real_v3/<name>/split.json.
run: one record per repository, method and run in results/raw/real_v3/<name>/<method>-r<run>/
(report.json, final.diff, summary.json, heldout.json; for the agent team also the run's
events.jsonl and reports, as exp_case_study.py records them, so the review and the diff audit
read them the same way). The held-out check applies the final diff to the base commit and runs
the held-out modules again: a module that passed before and fails after is a behavior change.
Run 2 (only on the repositories the split marks for two runs) uses its own LLM cache, so it is
a second model run, not a replay.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from methods_v3 import LABELS, resolve, run_method  # noqa: E402

RAW = ROOT / "results" / "raw" / "real_v3"
SPLIT = ROOT / "data" / "splits" / "v3_repos.json"
CLONES = "data/raw/aidev/heldout"
SEED = 4
BUDGET = {"minutes": 120}
METHODS = [
    "agentic",
    "agentic-batch",
    "agentic-no_research",
    "agentic-single_agent",
    "aider",
    "cleansweep",
]
GIT = ["git", "-c", "user.name=bench", "-c", "user.email=bench@example.com"]
COPY = ["CLEANUP_REPORT.md", "blueprint.md", "PR_DESCRIPTION.md", "events.jsonl"]


def real_repos(split: Path = SPLIT) -> dict[str, dict]:
    """{owner/name: its split entry} for the REAL set."""
    return {r["full_name"]: r for r in json.loads(split.read_text())["real"]}


def is_test_module(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def split_tests(files: list[str], seed: int = SEED) -> tuple[list[str], list[str]]:
    """(visible, held out): the test modules shuffled by the seed, the first half held out."""
    tests = sorted(f for f in files if is_test_module(f))
    random.Random(seed).shuffle(tests)
    held = sorted(tests[: len(tests) // 2])
    return sorted(set(tests) - set(held)), held


def _git(tree: Path, *args: str) -> str:
    return subprocess.run(
        [*GIT, *args], cwd=tree, capture_output=True, text=True, check=True
    ).stdout.strip()


def heldout_tree(full_name: str, head_sha: str, cfg: dict) -> Path:
    """The held-out clone with its "base" commit (the screened head), made once."""
    from cleansweep.data.swebench import data_path

    name = full_name.replace("/", "__")
    tree = data_path(CLONES) / name
    if (tree / ".git").exists():
        return tree
    clone = data_path(cfg["data"]["aidev"]["clones"]) / name
    tree.mkdir(parents=True)
    archive = subprocess.Popen(["git", "archive", head_sha], cwd=clone, stdout=subprocess.PIPE)
    subprocess.run(["tar", "-xf", "-", "-C", str(tree)], stdin=archive.stdout, check=True)
    if archive.wait() != 0:
        shutil.rmtree(tree, ignore_errors=True)
        raise RuntimeError(f"git archive failed for {full_name}@{head_sha}")
    _git(tree, "init", "-q")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "--no-verify", "-m", "base")
    return tree


def run_tests_at(target: str, tests: list[str], cfg: dict, diff: str = "") -> dict:
    """The given test modules at a target, optionally after a diff, in a fresh container."""
    from cleansweep.sandbox import open_workspace

    ws = open_workspace(target, cfg["core"].get("sandbox"))
    try:
        if diff.strip() and not ws.apply_patch(diff):
            return {"applied": False}
        result = ws.run_tests(tests)
        return {
            "applied": True,
            "ok": result.ok,
            "passed": result.passed,
            "failed": result.failed,
            "errors": result.errors,
            "failed_ids": sorted(result.failed_ids),
        }
    finally:
        ws.close()


def prepare(full_name: str, entry: dict, cfg: dict) -> dict:
    name = full_name.replace("/", "__")
    folder = RAW / name
    if (folder / "split.json").exists():
        return json.loads((folder / "split.json").read_text())
    tree = heldout_tree(full_name, entry["head_sha"], cfg)
    base = _git(tree, "rev-list", "--max-parents=0", "HEAD").split()[0]
    _git(tree, "checkout", "-q", "--detach", base)
    visible, held = split_tests(_git(tree, "ls-files").splitlines())
    split = {"full_name": full_name, "seed": SEED, "base": base, "visible": visible, "held": held}
    if len(held) < 1 or len(visible) < 1:
        split["skip"] = "fewer than two test modules: nothing to hold out"
    else:
        for path in held:
            (tree / path).unlink()
        _git(tree, "add", "-A")
        _git(tree, "commit", "-q", "--no-verify", "-m", f"hold out tests (seed {SEED})")
        split["visible_sha"] = _git(tree, "rev-parse", "HEAD")
        _git(tree, "tag", "-f", "visible", split["visible_sha"])
        split["baseline"] = run_tests_at(f"aidev:{full_name}@{base}", held, cfg)
        if not split["baseline"].get("passed"):
            split["skip"] = "no held-out test passes before any cleanup"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "split.json").write_text(json.dumps(split, indent=1))
    return split


def heldout_check(full_name: str, split: dict, diff: str, cfg: dict) -> dict:
    """The held-out modules on the base commit after the final diff, against their baseline."""
    after = run_tests_at(f"aidev:{full_name}@{split['base']}", split["held"], cfg, diff)
    if not after.get("applied"):
        return {"applied": False, "behavior_changed": None}
    newly = sorted(set(after["failed_ids"]) - set(split["baseline"]["failed_ids"]))
    return {
        **after,
        "newly_failing": newly,
        "behavior_changed": bool(newly) or after["passed"] < split["baseline"]["passed"],
    }


def run_cfg(run: int, folder: Path) -> dict:
    from cleansweep.core.config import load_config

    over = {
        "reviewer": {"scope": "repo"},
        "core": {"sandbox": {"aidev_clones": CLONES}, "agents": {"budget": BUDGET}},
    }
    if run > 1:  # its own caches: a second model run, not a replay of the first
        caches = folder / "caches"
        over["core"]["llm"] = {"cache_path": str(caches / "llm.sqlite")}
        over["core"]["guard"] = {"probe_cache_dir": str(caches / "probes")}
    return load_config(over)


def summarize(report, minutes: float) -> dict:
    """The record's numbers; the team's runs also get exp_case_study.py's full record."""
    stats = report.stats
    return {
        "project": report.repo_id,
        "verdict": stats.get("agentic", {}).get("verdict", stats.get("verdict", "")),
        "lines_removed": stats.get("lines_removed"),
        "files_removed": stats.get("files_removed"),
        "llm_requests": stats.get("llm_calls"),
        "prompt_tokens": stats.get("prompt_tokens"),
        "completion_tokens": stats.get("completion_tokens"),
        "test_runs": stats.get("test_runs"),
        "minutes": minutes,
    }


def _case_study():
    path = ROOT / "scripts" / "experiments" / "v2" / "exp_case_study.py"
    spec = importlib.util.spec_from_file_location("exp_case_study", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_one(full_name: str, split: dict, label: str, run: int) -> dict:
    from cleansweep.core.io import save_json

    folder = RAW / full_name.replace("/", "__") / f"{label}-r{run}"
    folder.mkdir(parents=True, exist_ok=True)
    cfg = run_cfg(run, folder)
    out = Path(tempfile.mkdtemp(prefix="cs_real_"))
    t0 = time.time()
    try:
        report = run_method(f"aidev:{full_name}@{split['visible_sha']}", label, cfg, out)
        minutes = round((time.time() - t0) / 60, 2)
        save_json(report, folder / "report.json")
        diff = report.stats.get("final_diff", "")
        (folder / "final.diff").write_text(diff)
        summary = summarize(report, minutes)
        if resolve(label).kind == "agentic":
            result = {
                "out": str(out),
                "report": report,
                "summary": {"verdict": summary["verdict"]},
                "branch": None,
                "workspace": None,
            }
            summary = {**_case_study().record(result, time.time() - t0), **summary}
            for name in COPY:
                if (out / name).exists():
                    shutil.copy(out / name, folder / name)
        (folder / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    finally:
        shutil.rmtree(out, ignore_errors=True)
    held = heldout_check(full_name, split, diff, cfg)
    (folder / "heldout.json").write_text(json.dumps(held, indent=1))
    return {
        "repo": full_name,
        "method": label,
        "run": run,
        "minutes": minutes,
        "verdict": summary["verdict"],
        "lines_removed": summary["lines_removed"],
        "heldout_changed": held.get("behavior_changed"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["prepare", "run"])
    parser.add_argument("--repos", nargs="+")
    parser.add_argument("--methods", nargs="+", default=METHODS, choices=LABELS)
    parser.add_argument("--run", type=int, default=1, choices=[1, 2])
    args = parser.parse_args(argv)
    from cleansweep.core.config import load_config
    from cleansweep.sandbox.cleanup import on_start

    on_start()
    cfg = load_config({"core": {"sandbox": {"aidev_clones": CLONES}}})
    repos = real_repos()
    for full_name in args.repos or list(repos):
        entry = repos[full_name]
        try:
            split = prepare(full_name, entry, cfg)
        except Exception as exc:  # record and go on
            print(f"error prepare {full_name}: {type(exc).__name__}: {exc}", flush=True)
            continue
        if split.get("skip"):
            print(f"skip {full_name}: {split['skip']}", flush=True)
            continue
        if args.what == "prepare" or (args.run == 2 and entry.get("runs", 1) < 2):
            continue
        for label in args.methods:
            folder = RAW / full_name.replace("/", "__") / f"{label}-r{args.run}"
            if (folder / "heldout.json").exists():
                continue
            try:
                print(json.dumps(run_one(full_name, split, label, args.run)), flush=True)
            except Exception as exc:  # record and go on; a rerun retries it
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "error.txt").write_text(traceback.format_exc())
                print(f"error {full_name} {label}: {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
