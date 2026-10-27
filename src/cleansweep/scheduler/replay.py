"""Replay a repository's history under a sweep policy, with static detectors only.

Slop is measured at up to `replay_points` commits spread over the history (plus the last), by
the cheap static detectors (leftover files, dead code, unused imports, wrappers), and cached per
commit; between two measured commits the slop is taken from the earlier one. A sweep removes
all slop present at that commit. Nothing from the repository is run: its files are only
extracted (git archive) and parsed.
"""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from pathlib import Path

from cleansweep.core.models import CommitEvent

from .policies import should_sweep

REMOVABLE = {"leftover_file", "dead_code", "unused_import", "wrapper"}
DEFAULTS = {
    "replay_points": 40,
    "every_n": 5,
    "adaptive_threshold": 0.02,
    "batch_max_size": 8,
    "slop_cache": "data/processed/aidev_slop",
}


def _setting(cfg: dict | None, key: str):
    return (cfg or {}).get(key, DEFAULTS[key])


def measure(repo_dir: str, sha: str) -> dict:
    """Static slop at one commit: {"items": {item_id: [category, unit_key, lines]},
    "loc": python lines, "files": python files}."""
    from cleansweep.analysis import build_graph
    from cleansweep.analysis.graph import iter_py_files
    from cleansweep.reviewer.detectors import (
        _settings,
        detect_dead_code,
        detect_leftovers,
        detect_unused_imports,
        detect_wrappers,
    )

    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.Popen(["git", "archive", sha], cwd=repo_dir, stdout=subprocess.PIPE)
        subprocess.run(["tar", "-xf", "-", "-C", tmp], stdin=archive.stdout, check=True)
        archive.wait()
        files = iter_py_files(tmp)
        lines = {}
        for f in files:
            try:
                lines[f] = len(
                    (Path(tmp) / f).read_text(encoding="utf-8", errors="replace").splitlines()
                )
            except OSError:
                lines[f] = 0
        graph = build_graph(tmp)
        cfg = _settings()
        found = [
            *detect_leftovers(tmp, graph, cfg["leftover_patterns"]),
            *detect_dead_code(tmp, graph, cfg["vulture_min_confidence"]),
            *detect_unused_imports(tmp),
            *detect_wrappers(tmp, graph),
        ]
    items = {}
    for item in found:
        if item.category not in REMOVABLE or item.lane != "safe":
            continue
        unit = item.unit
        size = (
            lines.get(unit.path, 1)
            if unit.kind == "file"
            else ((unit.end_line or unit.start_line or 0) - (unit.start_line or 0) + 1)
        )
        items[item.item_id] = [item.category, unit.key, max(size, 1)]
    return {"items": items, "loc": sum(lines.values()), "files": sorted(lines)}


def measured_points(history: list[CommitEvent], points: int) -> list[int]:
    """Indexes of the commits to measure: evenly spread, always including the last."""
    n = len(history)
    if n == 0:
        return []
    step = max(1, math.ceil(n / points))
    return sorted(set(range(0, n, step)) | {n - 1})


def snapshots(
    history: list[CommitEvent], repo_dir: str, cfg: dict | None = None
) -> dict[int, dict]:
    """Measured slop per commit index, cached on disk per commit sha."""
    from cleansweep.data.swebench import data_path

    cache = data_path(_setting(cfg, "slop_cache")) / Path(repo_dir).name
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    for i in measured_points(history, int(_setting(cfg, "replay_points"))):
        path = cache / f"{history[i].sha}.json"
        if path.exists():
            out[i] = json.loads(path.read_text())
        else:
            out[i] = measure(repo_dir, history[i].sha)
            path.write_text(json.dumps(out[i]))
    return out


def simulate(
    history: list[CommitEvent], repo_dir: str, policy: str, cfg: dict | None = None
) -> dict:
    """Replay the history under a policy (every_pr, every_n, daily, adaptive, or none).

    every_pr, every_n and adaptive sweep right after the commit that triggers them; daily
    sweeps at the first commit of a new UTC day, before that commit lands.

    Returns slop debt (sum over commits of open slop items), final slop, sweeps, estimated test
    runs (a baseline and one per batch of batch_max_size), the resurrection rate (removed
    functions, classes and imports whose code still exists at the end but is no longer flagged:
    a later commit started using them), and the slop curve."""
    snaps = snapshots(history, repo_dir, cfg)
    if not snaps:
        return {"policy": policy, "commits": 0}
    measured = sorted(snaps)
    batch = int(_setting(cfg, "batch_max_size"))
    removed: dict[str, tuple[int, list]] = {}
    sweeps = test_runs = debt = 0
    prs_since = commits_since = 0
    last_sweep_time = None
    curve = []
    current = snaps[measured[0]]
    for i, commit in enumerate(history):
        nightly = False
        if policy == "daily" and i > 0:
            # a nightly sweep runs at the day boundary: on what the earlier days left open,
            # before this commit lands
            before = {k: v for k, v in current["items"].items() if k not in removed}
            day_state = {"now": commit.timestamp, "last_sweep_time": history[i - 1].timestamp}
            if before and should_sweep("daily", day_state):
                nightly = True
                sweeps += 1
                test_runs += 1 + math.ceil(len(before) / batch)
                removed.update({k: (i, v) for k, v in before.items()})
                prs_since = commits_since = 0
                last_sweep_time = commit.timestamp
        if i in snaps:
            current = snaps[i]
        commits_since += 1
        prs_since += bool(commit.is_agent and commit.pr_number)  # agent pull requests only
        open_items = {k: v for k, v in current["items"].items() if k not in removed}
        state = {
            "prs_since_sweep": prs_since,
            "commits_since_sweep": commits_since,
            "n": int(_setting(cfg, "every_n")),
            "now": commit.timestamp,
            "last_sweep_time": last_sweep_time,
            "repo_loc": current["loc"],
            "slop_loc": sum(v[2] for v in open_items.values()),
            "threshold": float(_setting(cfg, "adaptive_threshold")),
        }
        swept = policy not in ("none", "daily") and bool(open_items) and should_sweep(policy, state)
        if swept:
            sweeps += 1
            test_runs += 1 + math.ceil(len(open_items) / batch)
            removed.update({k: (i, v) for k, v in open_items.items()})
            open_items = {}
            prs_since = commits_since = 0
            last_sweep_time = commit.timestamp
        debt += len(open_items)
        curve.append(
            {
                "index": i,
                "sha": commit.sha,
                "timestamp": commit.timestamp,
                "open_slop": len(open_items),
                "swept": bool(swept or nightly),
                "loc": current["loc"],
            }
        )
    final = snaps[measured[-1]]
    final_files = set(final["files"])
    resurrected = sum(
        1
        for key, (_, (category, unit_key, _)) in removed.items()
        if key not in final["items"] and unit_key.split("::")[0] in final_files and "::" in unit_key
    )
    removable_units = sum(1 for _, (_, (c, u, _)) in removed.items() if "::" in u)
    return {
        "policy": policy,
        "commits": len(history),
        "measured_commits": len(measured),
        "sweeps": sweeps,
        "test_runs_est": test_runs,
        "slop_debt": debt,
        "slop_debt_per_commit": round(debt / len(history), 3),
        "final_slop": curve[-1]["open_slop"],
        "removed": len(removed),
        "resurrected": resurrected,
        "resurrection_rate": round(resurrected / removable_units, 3) if removable_units else 0.0,
        "curve": curve,
    }
