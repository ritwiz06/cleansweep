"""What the coding agent wrote: the units and lines its "agent patch" commit added or changed.

SWE-bench workspaces (and any repo with such a commit) have a `base` commit and an
`agent patch` commit on top. Old code in a big project (Django has thousands of dead-code hits)
is not the agent's slop, so the Reviewer looks only inside this scope.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from cleansweep.core.models import CodeUnit

AGENT_COMMIT = "agent patch"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


@dataclass
class AgentScope:
    files_added: set[str] = field(default_factory=set)
    lines: dict[str, set[int]] = field(default_factory=dict)  # changed files -> new line numbers
    units: set[str] = field(default_factory=set)  # unit keys the agent wrote or changed
    base_dirs: set[str] = field(default_factory=set)  # top-level folders before the patch

    @property
    def files(self) -> set[str]:
        return self.files_added | set(self.lines)

    def outside_project(self, path: str) -> bool:
        """A file the agent created at the repo root or in a folder it created."""
        top, sep, _ = path.partition("/")
        return path in self.files_added and (not sep or top not in self.base_dirs)

    def covers_line(self, path: str, line: int) -> bool:
        return path in self.files_added or line in self.lines.get(path, ())

    def covers(self, unit: CodeUnit) -> bool:
        """True if the agent wrote or changed this unit."""
        if unit.path in self.files_added:
            return True
        if unit.kind in ("file", "function", "class"):
            return unit.key in self.units
        changed = self.lines.get(unit.path)
        if changed is None:
            return False
        if unit.kind == "dependency":
            return True  # the agent edited this dependency file
        start = unit.start_line or 0
        return any(line in changed for line in range(start, (unit.end_line or start) + 1))


def agent_commit(repo_dir: str) -> str | None:
    """The sha of the "agent patch" commit, or None if the repo has none."""
    out = subprocess.run(
        ["git", "log", "--format=%H %s"], cwd=repo_dir, capture_output=True, text=True
    ).stdout
    for line in out.splitlines():
        sha, _, subject = line.partition(" ")
        if subject == AGENT_COMMIT:
            return sha
    return None


def _code_lines(repo_dir: str, path: str, lines: set[int]) -> set[int]:
    """Drop blank and comment lines: a new method's surrounding blank lines don't make its
    class 'changed'."""
    try:
        text = (Path(repo_dir) / path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return lines
    return {n for n in lines if 0 < n <= len(text) and text[n - 1].strip()[:1] not in ("", "#")}


def _changes(repo_dir: str, sha: str) -> tuple[set[str], dict[str, set[int]]]:
    status = subprocess.run(
        ["git", "diff", "--name-status", f"{sha}~1", sha],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    ).stdout
    added, modified = set(), set()
    for line in status.splitlines():
        code, _, path = line.partition("\t")
        (added if code.startswith("A") else modified).add(path.split("\t")[-1])
    lines: dict[str, set[int]] = {}
    for path in sorted(modified):
        diff = subprocess.run(
            ["git", "diff", "-U0", f"{sha}~1", sha, "--", path],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        ).stdout
        changed = set()
        for m in HUNK.finditer(diff):
            start, count = int(m.group(1)), int(m.group(2) or 1)
            # a pure deletion (count 0) marks the line it happened after
            changed.update(range(start, start + count) if count else [start])
        lines[path] = _code_lines(repo_dir, path, changed)
    return added, lines


def agent_scope(repo_dir: str, graph) -> AgentScope | None:
    """The agent's files, changed lines and units; None when there is no agent patch commit."""
    sha = agent_commit(repo_dir)
    if sha is None:
        return None
    added, lines = _changes(repo_dir, sha)
    tree = subprocess.run(
        ["git", "ls-tree", "-d", "--name-only", f"{sha}~1"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    ).stdout
    scope = AgentScope(added, lines, base_dirs=set(tree.split()))
    for unit in graph.units():
        if unit.path in added:
            scope.units.add(unit.key)
            continue
        changed = lines.get(unit.path)
        if not changed or unit.kind == "file" or not unit.start_line or not unit.end_line:
            continue
        span = set(range(unit.start_line, unit.end_line + 1))
        if not span & changed:
            continue
        # a class counts only for changes outside its methods (its methods count themselves)
        inner = [
            u
            for u in graph.units()
            if u.path == unit.path and u.key != unit.key and u.key.startswith(unit.key + ".")
        ]
        own = span.difference(*(range(u.start_line, (u.end_line or 0) + 1) for u in inner))
        if own & changed:
            scope.units.add(unit.key)
    return scope
