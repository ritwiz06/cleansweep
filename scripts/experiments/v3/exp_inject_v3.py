"""Out-of-sample injection (v3): v2's slop-injection benchmark on the INJECT repositories of
data/splits/v3_repos.json, at a fresh seed (4), for the v3 methods (methods_v3.py).

    python scripts/experiments/v3/exp_inject_v3.py prepare [--repos owner/name ...] [--seeds 4]
    python scripts/experiments/v3/exp_inject_v3.py run [--repos owner/name ...] [--seeds 4]
        [--methods agentic agentic-no_resolver ...]
    python scripts/experiments/v3/exp_inject_v3.py table

prepare: the plants, their checks and the hidden test's baseline only (no method runs), so the
runs can start from keys made ahead of time; a repository with nowhere to plant is listed, and
the split's reserve replaces it.

Reuses scripts/experiments/v2/exp_inject.py (plants, plant checks, the hidden test, scoring) with
its own raw folder (results/raw/inject_v3/) and tables (results/summary/v3/injection.csv and
injection_summary.csv), so v2's tables never see a v3 run. Each repository's injected clone sits
beside v2's in data/raw/aidev/injected/, based at the head the v3 screen recorded. The resolver
and batching gains are claimed only from these runs (out of sample).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
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
from methods_v3 import LABELS, Capped, run_method  # noqa: E402

RAW = ROOT / "results" / "raw" / "inject_v3"
SUMMARY = ROOT / "results" / "summary" / "v3"
SPLIT = ROOT / "data" / "splits" / "v3_repos.json"
SEEDS = [4]
METHODS = [
    "agentic",
    "agentic-no_resolver",
    "agentic-batch",
    "agentic-no_research",
    "agentic-single_agent",
    "aider",
    "cleansweep",
]


def load_v2():
    """v2's exp_inject, writing to the v3 folders and basing clones on the v3 heads."""
    path = ROOT / "scripts" / "experiments" / "v2" / "exp_inject.py"
    spec = importlib.util.spec_from_file_location("exp_inject_v2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RAW, module.SUMMARY = RAW, SUMMARY
    module._injected_base = lambda repo, name, cfg: injected_base(module, repo, name, cfg)
    return module


def inject_repos(split: Path = SPLIT) -> dict[str, str]:
    """{owner/name: head sha} of the INJECT set."""
    return {r["full_name"]: r["head_sha"] for r in json.loads(split.read_text())["inject"]}


def injected_base(v2, repo: str, name: str, cfg: dict) -> Path:
    """The injected clone, checked out clean at its base commit: the v3 screen's head."""
    from cleansweep.data.swebench import data_path

    tree = data_path(v2.CLONES) / name
    if not (tree / ".git").exists():
        clone = data_path(cfg["data"]["aidev"]["clones"]) / name
        with tempfile.TemporaryDirectory() as tmp:
            archive = subprocess.Popen(
                ["git", "archive", inject_repos()[repo]], cwd=clone, stdout=subprocess.PIPE
            )
            subprocess.run(["tar", "-xf", "-", "-C", tmp], stdin=archive.stdout, check=True)
            archive.wait()
            v2._git_tree(Path(tmp), tree)
        return tree
    v2._tag_prepared(tree, name)
    base = v2._git(tree, "rev-list", "--max-parents=0", "HEAD").split()[0]
    v2._git(tree, "checkout", "-q", "--detach", base)
    v2._git(tree, "reset", "-q", "--hard")
    v2._git(tree, "clean", "-qfdx")
    return tree


def run_one(v2, repo: str, seed: int, label: str, cfg: dict) -> dict:
    from cleansweep.core.io import save_json
    from cleansweep.data.swebench import data_path

    name = repo.replace("/", "__")
    folder = RAW / f"{name}-s{seed}"
    key = json.loads((folder / "key.json").read_text())
    target = key["target"]
    tree = data_path(v2.CLONES) / name
    sha = key.get("sha") or target.partition("@")[2]
    t0 = time.time()
    try:
        report = run_method(target, label, cfg, folder / f"{label}_run")
    except Capped as exc:  # recorded without a score: v2's table skips it, the v3 table counts it
        minutes = round((time.time() - t0) / 60, 2)
        stats = {"capped": str(exc), "minutes": minutes}
        (folder / f"{label}.json").write_text(json.dumps({"method": label, "stats": stats}))
        return {"repo": repo, "seed": seed, "method": label, "minutes": minutes, "capped": True}
    minutes = round((time.time() - t0) / 60, 2)
    diff = report.stats.get("final_diff", "")
    after, applied = v2.final_tree(tree, diff, sha)
    try:
        scored = v2.score(after, key)
    finally:
        shutil.rmtree(after.parent, ignore_errors=True)
    hidden = v2.hidden_check(target, diff, folder / "hidden", cfg)
    report.stats.update(
        minutes=minutes, inject={"applied": applied, "plants": scored}, hidden=hidden
    )
    save_json(report, folder / f"{label}.json")
    return {
        "repo": repo,
        "seed": seed,
        "method": label,
        "minutes": minutes,
        "removed": sum(p["removed"] for p in scored if p["kind"] == "slop"),
        "traps_removed": sum(p["removed"] for p in scored if p["kind"] == "trap"),
        "hidden_changed": hidden.get("behavior_changed"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["prepare", "run", "table"])
    parser.add_argument("--repos", nargs="+")
    parser.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    parser.add_argument("--methods", nargs="+", default=METHODS, choices=LABELS)
    args = parser.parse_args(argv)
    v2 = load_v2()
    if args.what == "table":
        print(*v2.table(), sep="\n")
        return 0
    from cleansweep.core.config import load_config
    from cleansweep.sandbox.cleanup import on_start

    on_start()
    cfg = load_config(
        {"reviewer": {"scope": "repo"}, "core": {"sandbox": {"aidev_clones": v2.CLONES}}}
    )
    for repo in args.repos or list(inject_repos()):
        for seed in args.seeds:
            folder = RAW / f"{repo.replace('/', '__')}-s{seed}"
            if not (folder / "key.json").exists():
                try:
                    v2.prepare(repo, seed, cfg)
                except ValueError as exc:  # nowhere to plant, or no valid draw: left out
                    print(f"skip {repo}: {exc}", flush=True)
                    continue
            for label in [] if args.what == "prepare" else args.methods:
                if (folder / f"{label}.json").exists():
                    continue
                try:
                    print(json.dumps(run_one(v2, repo, seed, label, cfg)), flush=True)
                except Exception as exc:  # record and go on; a rerun retries it
                    errors = folder / "errors"
                    errors.mkdir(exist_ok=True)
                    (errors / f"{label}.txt").write_text(traceback.format_exc())
                    print(f"error {repo} {label}: {type(exc).__name__}: {exc}", flush=True)
    if args.what == "run":
        print(*v2.table(), sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
