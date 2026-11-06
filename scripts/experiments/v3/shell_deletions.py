"""What Aider meant to delete, done after it exits: the deletions among the shell commands it
proposed (which auto-yes declined), that is rm or git rm with only -r/-f flags on plain relative
paths that exist in the workspace (everything else is refused and recorded with the reason); and
the files it emptied, its other way to remove a leftover file."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path, PurePosixPath

DELETE_FLAGS = {"-r", "-f", "-rf", "-fr", "-R"}
NOT_PLAIN = re.compile(r"[*?\[\]{}~$`|&;<>\\]")  # globs, expansions, pipes, redirects


def deletion_paths(part: str, root: Path) -> list[Path] | str:
    """The paths one shell command deletes, or why it is refused: rm or git rm with only -r/-f
    flags, on plain relative paths that exist in the workspace (no globs, .., absolute paths or
    .git)."""
    try:
        words = shlex.split(part)
    except ValueError:
        return "does not parse"
    if words[:2] == ["git", "rm"]:
        words = words[2:]
    elif words[:1] == ["rm"]:
        words = words[1:]
    else:
        return "not a deletion"
    flags = [w for w in words if w.startswith("-")]
    names = [w for w in words if not w.startswith("-")]
    if set(flags) - DELETE_FLAGS:
        return "a flag other than -r or -f"
    if not names:
        return "no path"
    paths = []
    for name in names:
        rel = PurePosixPath(name)
        odd = rel.is_absolute() or not rel.parts or ".." in rel.parts or rel.parts[0] == ".git"
        if odd or NOT_PLAIN.search(name):
            return f"not a plain relative path: {name}"
        path = root / rel
        inside = path.parent.resolve().is_relative_to(root.resolve())
        if not inside or not (path.exists() or path.is_symlink()):
            return f"not in the workspace: {name}"
        if path.is_dir() and not path.is_symlink() and not any("r" in f.lower() for f in flags):
            return f"a folder without -r: {name}"
        paths.append(path)
    return paths


def run_deletions(commands: list[str], root: Path) -> dict:
    """Run the deletions among Aider's proposed shell commands (chains split at &&, || and ;);
    record the parts run and the parts refused with the reason."""
    executed, refused, seen = [], [], set()
    for command in commands:
        for line in command.splitlines():
            for part in re.split(r"&&|\|\||;", line):
                part = part.strip()
                if not part or part.startswith("#") or part in seen:
                    continue
                seen.add(part)
                paths = deletion_paths(part, root)
                if isinstance(paths, str):
                    refused.append({"command": part, "reason": paths})
                    continue
                for path in paths:
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    elif path.exists() or path.is_symlink():  # gone when named twice
                        path.unlink()
                executed.append(part)
    return {"executed": executed, "refused": refused}


def delete_emptied(root: Path, base: str) -> list[str]:
    """Delete the files left empty or whitespace-only that were not empty at the base commit;
    return their paths."""
    git = ["git", "-c", "core.quotePath=false"]
    changed = subprocess.run(
        [*git, "diff", "-z", "--name-only", base], cwd=root, capture_output=True, check=True
    ).stdout.decode()
    emptied = []
    for rel in filter(None, changed.split("\0")):
        path = root / rel
        if path.is_symlink() or not path.is_file() or path.read_bytes().strip():
            continue
        before = subprocess.run([*git, "show", f"{base}:{rel}"], cwd=root, capture_output=True)
        if before.stdout.strip():
            path.unlink()
            emptied.append(rel)
    return emptied
