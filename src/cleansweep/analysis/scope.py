"""What the coding agent wrote: the units and lines its "agent patch" commit added or changed.

SWE-bench workspaces (and any repo with such a commit) have a `base` commit and an
`agent patch` commit on top. Old code in a big project (Django has thousands of dead-code hits)
is not the agent's slop, so the Reviewer looks only inside this scope.

AIDev workspaces have no such commit; their scope comes from git blame on the repository's
history (`blame_scope`) and is stored in the workspace's .git folder (SCOPE_FILE).
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from cleansweep.core.models import CodeUnit

AGENT_COMMIT = "agent patch"
SCOPE_FILE = "cs_agent_scope.json"  # in .git/ of a workspace without an agent patch commit
BLAME = re.compile(r"^([0-9a-f]{40}) \d+ (\d+) (\d+)$", re.MULTILINE)
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


@dataclass
class AgentScope:
    files_added: set[str] = field(default_factory=set)
    lines: dict[str, set[int]] = field(default_factory=dict)  # changed files -> new line numbers
    units: set[str] = field(default_factory=set)  # unit keys the agent wrote or changed
    base_dirs: set[str] = field(default_factory=set)  # top-level folders before the patch
    scratch_rule: bool = True  # files outside the project count as the agent's scratch

    @property
    def files(self) -> set[str]:
        return self.files_added | set(self.lines)

    def outside_project(self, path: str) -> bool:
        """A file the agent created at the repo root or in a folder it created."""
        if not self.scratch_rule:
            return False
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


def blame_scope(clone: str, head: str, agent_shas: set[str], window_start: str | None) -> dict:
    """What agent commits wrote, by first-parent git blame at `head`: the files they created that
    still exist, and in the other files they touched, the lines they wrote. Blame stops at
    `window_start` (the oldest commit of the history that marks agent commits); older lines
    count as not the agent's."""

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=clone, capture_output=True, text=True).stdout

    at_head = set(git("ls-tree", "-r", "--name-only", head).split("\n"))
    added, touched = set(), set()
    for sha in sorted(agent_shas):
        for line in git("diff", "--name-status", "--no-renames", f"{sha}^1", sha).splitlines():
            code, _, path = line.partition("\t")
            (added if code == "A" else touched).add(path)
    added &= at_head
    # a root commit has no parent to stop at: then blame goes back to the start
    has_parent = window_start and git("rev-parse", "--verify", "-q", f"{window_start}^").strip()
    span = [f"{window_start}^..{head}"] if has_parent else [head]
    lines: dict[str, list[int]] = {}
    for path in sorted((touched & at_head) - added):
        out = git("blame", "--first-parent", "--incremental", *span, "--", path)
        mine = [
            n
            for m in BLAME.finditer(out)
            if m.group(1) in agent_shas
            for n in range(int(m.group(2)), int(m.group(2)) + int(m.group(3)))
        ]
        if mine:
            lines[path] = sorted(mine)
    return {"files_added": sorted(added), "lines": lines}


def _add_units(scope: AgentScope, graph) -> AgentScope:
    """Unit keys the agent wrote or changed, from its files and lines."""
    for unit in graph.units() if graph is not None else []:
        if unit.path in scope.files_added:
            scope.units.add(unit.key)
            continue
        changed = scope.lines.get(unit.path)
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


def _stored_scope(repo_dir: str) -> AgentScope | None:
    """The blame scope an AIDev workspace stores in .git/ (see blame_scope)."""
    path = Path(repo_dir) / ".git" / SCOPE_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    lines = {p: set(ns) for p, ns in data["lines"].items()}
    # merged pull requests went through review: their new files are not scratch files
    return AgentScope(set(data["files_added"]), lines, scratch_rule=False)


def scope_stats(repo_dir: str, scope: AgentScope | None, wanted: bool) -> dict:
    """The scope a sweep used, for its report. kind: "agent_patch" (the agent patch commit),
    "agent_blame" (the stored AIDev scope), "repo" (the whole repository), or "missing" when an
    agent scope was wanted but none was found. With a scope: its files and units, the Python lines
    the agent wrote and their share of the repository's Python lines."""
    from cleansweep.analysis.graph import iter_py_files

    if scope is None:
        return {"kind": "missing" if wanted else "repo"}
    py_lines = {}
    for path in iter_py_files(repo_dir):
        text = (Path(repo_dir) / path).read_text(encoding="utf-8", errors="replace")
        py_lines[path] = len(text.splitlines())
    agent = sum(py_lines.get(p, 0) for p in scope.files_added) + sum(
        len(lines) for p, lines in scope.lines.items() if p.endswith(".py")
    )
    total = sum(py_lines.values())
    return {
        "kind": "agent_patch" if agent_commit(repo_dir) else "agent_blame",
        "files": len(scope.files),
        "units": len(scope.units),
        "agent_py_lines": agent,
        "py_lines": total,
        "share": round(agent / total, 3) if total else 0.0,
    }


def agent_scope(repo_dir: str, graph=None) -> AgentScope | None:
    """The agent's files, changed lines and units (with a graph); None without an agent patch
    commit or a stored blame scope."""
    sha = agent_commit(repo_dir)
    if sha is None:
        stored = _stored_scope(repo_dir)
        return _add_units(stored, graph) if stored is not None else None
    added, lines = _changes(repo_dir, sha)
    tree = subprocess.run(
        ["git", "ls-tree", "-d", "--name-only", f"{sha}~1"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    ).stdout
    return _add_units(AgentScope(added, lines, base_dirs=set(tree.split())), graph)
