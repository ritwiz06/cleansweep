"""Share of each runnable AIDev repository's Python lines that the agent scope covers.

python scripts/data_aidev_scope.py [--extend owner/name ...] [--max-commits 3000]
    [--backfill FOLDER ...]

Reads data/splits/aidev_repos.json and each repository's clone (scripts/data_aidev_select.py)
at its head sha. The agent scope is what agent pull requests wrote, by first-parent blame
(cleansweep.analysis.scope.blame_scope): the files they created that still exist, and the lines
they wrote in the other files. A repository without an agent commit in its recorded history has
no scope, and the detectors then run on the whole repository. --extend first caches a longer
first-parent history for those repositories (cleansweep.data.aidev.extend_history: back to the
oldest agent commit within --max-commits), which only the agent scope reads. Writes
results/data_summary/aidev_scope.csv, with the history window each scope comes from.

--backfill adds the "scope used" record (stats["scope"]) to AIDev sweep reports written before
sweeps recorded it. The scope is rebuilt from the same history and checked against the report's
plan: if any item lies outside the agent's files, the run did not use the scope and is marked
"missing". Reports that have the record are left alone.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

from cleansweep.analysis.graph import build_graph
from cleansweep.analysis.scope import AgentScope, add_units, blame_scope
from cleansweep.core.config import load_config
from cleansweep.data.aidev import agent_history, extend_history
from cleansweep.data.swebench import data_path
from cleansweep.sandbox.aidev_docker import clone_dir

ROOT = Path(__file__).resolve().parents[1]
SPLIT = ROOT / "data" / "splits" / "aidev_repos.json"
OUT = ROOT / "results" / "data_summary" / "aidev_scope.csv"


def python_lines(clone: Path, sha: str) -> dict[str, int]:
    """Lines per Python file at sha."""
    out = subprocess.run(
        ["git", "grep", "-c", "", sha, "--", "*.py"], cwd=clone, capture_output=True, text=True
    ).stdout
    lines = {}
    for line in out.splitlines():
        path, n = line.removeprefix(f"{sha}:").rsplit(":", 1)
        lines[path] = int(n)
    return lines


def scope_share(py_lines: dict[str, int], scope: dict) -> dict:
    """Python lines in the files agent commits created and the lines they wrote in other files,
    and their share of the repository's Python lines."""
    new = sum(py_lines.get(p, 0) for p in scope["files_added"] if p.endswith(".py"))
    changed = sum(len(v) for p, v in scope["lines"].items() if p.endswith(".py"))
    total = sum(py_lines.values())
    return {
        "py_files": len(py_lines),
        "py_lines": total,
        "agent_py_files": sum(p.endswith(".py") for p in scope["files_added"]),
        "agent_file_lines": new,
        "agent_changed_lines": changed,
        "share": round((new + changed) / total, 3) if total else "",
    }


def items_outside(plan_items: list[dict], scope: dict) -> int:
    """Plan items whose file is not one the agent created or wrote lines in (the whole-repo
    ruff item of tools_only, path ".", doesn't count)."""
    files = set(scope["files_added"]) | set(scope["lines"])
    return sum(i["unit"]["path"] not in files for i in plan_items if i["unit"]["path"] != ".")


def scope_units(clone: Path, sha: str, scope: dict) -> int:
    """Units (classes and functions) the agent wrote or changed, on the code graph at sha."""
    with tempfile.TemporaryDirectory() as tmp:
        tar = Path(tmp) / "tree.tar"
        tar.write_bytes(
            subprocess.run(
                ["git", "archive", "--format=tar", sha], cwd=clone, capture_output=True, check=True
            ).stdout
        )
        with tarfile.open(tar) as f:
            f.extractall(Path(tmp) / "tree", filter="data")
        lines = {p: set(v) for p, v in scope["lines"].items()}
        agent = AgentScope(set(scope["files_added"]), lines, scratch_rule=False)
        return len(add_units(agent, build_graph(str(Path(tmp) / "tree"))).units)


def backfill(folders: list[Path], cfg: dict, repos: dict[str, str]) -> int:
    """Write stats["scope"] into the AIDev reports in folders that lack it, and the scope's units
    into records an earlier backfill wrote without them; returns how many reports changed."""
    done, scopes = 0, {}
    for folder in folders:
        for path in sorted(folder.glob("*__*__*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            owner, name, _ = path.stem.rsplit("__", 2)
            full = f"{owner}/{name}"
            old = data["stats"].get("scope")
            if full not in repos or (old and (old["kind"] != "agent_blame" or "units" in old)):
                continue
            if full not in scopes:
                clone, sha = clone_dir(cfg, full), repos[full]
                shas, start = agent_history(full, sha)
                scope = blame_scope(str(clone), sha, shas, start) if shas else None
                units = scope_units(clone, sha, scope) if scope else None
                scopes[full] = (scope, python_lines(clone, sha), units)
            scope, py_lines, units = scopes[full]
            outside = items_outside(data["plan"]["items"], scope) if scope else None
            if old:
                record = {**old, "units": units}
            elif scope is None or outside:
                record = {"kind": "missing", "items_outside": outside}
            else:
                share = scope_share(py_lines, scope)
                record = {
                    "kind": "agent_blame",
                    "files": len(set(scope["files_added"]) | set(scope["lines"])),
                    "units": units,
                    "agent_py_lines": share["agent_file_lines"] + share["agent_changed_lines"],
                    "py_lines": share["py_lines"],
                    "share": share["share"],
                    "items_outside": 0,
                }
            data["stats"]["scope"] = {**record, "backfilled": True}
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            done += 1
    return done


def history_window(cfg: dict, name: str) -> int:
    """Commits in the history the scope comes from: the longer scope history if cached, else the
    300-commit one (0 without either)."""
    key = f"{name.replace('/', '__')}.json"
    for folder in (cfg.get("scope_history_cache"), cfg["history_cache"]):
        if folder and (data_path(folder) / key).exists():
            return len(json.loads((data_path(folder) / key).read_text()))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extend", nargs="*", default=[], help="repos to give a longer history")
    parser.add_argument("--max-commits", type=int, default=3000)
    parser.add_argument("--backfill", nargs="*", default=[], help="report folders to backfill")
    args = parser.parse_args(argv)
    cfg = {**load_config()["data"]["aidev"], **load_config()["core"]["sandbox"]}
    repos = json.loads(SPLIT.read_text(encoding="utf-8"))
    heads = {r["full_name"]: r["head_sha"] for r in repos}
    for name in args.extend:
        window = extend_history(name, heads[name], args.max_commits)
        print(f"{name}: scope history {window or 'not extended (no agent commit)'}", flush=True)
    if args.backfill:
        n = backfill([Path(f) for f in args.backfill], cfg, heads)
        print(f"scope record added to {n} reports")
        return 0
    rows = []
    for repo in repos:
        name, sha = repo["full_name"], repo["head_sha"]
        clone = clone_dir(cfg, name)
        shas, start = agent_history(name, sha)
        scope = (
            blame_scope(str(clone), sha, shas, start) if shas else {"files_added": [], "lines": {}}
        )
        row = {
            "repo": name,
            "agent_commits": len(shas),
            "window_commits": history_window(cfg, name),
            **scope_share(python_lines(clone, sha), scope),
        }
        print(f"{name}: share {row['share']} ({row['agent_commits']} agent commits)", flush=True)
        rows.append(row)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} repos -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
