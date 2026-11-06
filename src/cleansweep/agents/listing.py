"""The project's files before the cleanup, with their line counts (Studio draws the tree)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from cleansweep.core.io import save_json

NAME = "project_files.json"
MAX_BYTES = 2_000_000


def _lines(path: Path) -> int | None:
    """A text file's line count; None for binary, large or unreadable files."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def project_files(root: str | Path) -> list[dict]:
    """Every file git lists in the workspace (tracked, or untracked and not ignored)."""
    root = Path(root)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        env=env,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", errors="replace")
    names = sorted({name for name in listed.split("\0") if name})
    return [{"path": n, "lines": _lines(root / n)} for n in names if (root / n).is_file()]


def save_project_files(root: str | Path, out: str | Path) -> None:
    """Write project_files.json into the run folder; skipped when git cannot list the files."""
    try:
        files = project_files(root)
    except (OSError, subprocess.SubprocessError):
        return
    save_json({"files": files}, Path(out) / NAME)
