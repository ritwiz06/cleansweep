"""Share of each runnable AIDev repository's Python lines that the agent scope covers.

python scripts/data_aidev_scope.py

Reads data/splits/aidev_repos.json and each repository's clone (scripts/data_aidev_select.py)
at its head sha. The agent scope is what agent pull requests wrote, by first-parent blame
(cleansweep.analysis.scope.blame_scope): the files they created that still exist, and the lines
they wrote in the other files. A repository without an agent commit in its recorded history has
no scope, and the detectors then run on the whole repository. Writes
results/data_summary/aidev_scope.csv.
"""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

from cleansweep.analysis.scope import blame_scope
from cleansweep.core.config import load_config
from cleansweep.data.aidev import agent_history
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


def main() -> int:
    cfg = {**load_config()["data"]["aidev"], **load_config()["core"]["sandbox"]}
    rows = []
    for repo in json.loads(SPLIT.read_text(encoding="utf-8")):
        name, sha = repo["full_name"], repo["head_sha"]
        clone = clone_dir(cfg, name)
        shas, start = agent_history(name, sha)
        scope = (
            blame_scope(str(clone), sha, shas, start) if shas else {"files_added": [], "lines": {}}
        )
        row = {
            "repo": name,
            "agent_commits": len(shas),
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
