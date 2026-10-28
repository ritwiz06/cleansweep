from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .workspace import GIT_ID, Workspace

SKIP = shutil.ignore_patterns(
    ".git",
    "__pycache__",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".cleansweep",
    "*.pyc",
    ".coverage",
)


# generated files must never show up in checkpoints or diffs
WS_EXCLUDE = [
    "__pycache__/",
    "*.pyc",
    ".pytest_cache/",
    ".coverage*",
    "*.egg-info/",  # written by an editable install inside the workspace
    "_hidden_checks/",
    "_probes/",
    "test_cs_probe_*.py",
]


def default_work_dir(cfg: dict) -> Path:
    # Outside the cleansweep repo on purpose: pytest would otherwise pick up our pyproject.
    return Path(cfg.get("work_dir") or Path(tempfile.gettempdir()) / "cleansweep" / "ws")


def open_local(target: str, cfg: dict | None = None) -> Workspace:
    """Copy a local folder into a fresh git workspace with a 'base' checkpoint."""
    cfg = cfg or {}
    src = Path(target).resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"target folder not found: {target}")
    stamp = hashlib.sha1(f"{src}{time.time_ns()}".encode()).hexdigest()[:10]
    dest = default_work_dir(cfg) / f"{src.name}-{stamp}"
    shutil.copytree(src, dest, ignore=SKIP)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    (dest / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (dest / ".git" / "info" / "exclude").write_text("\n".join(WS_EXCLUDE) + "\n")
    subprocess.run(["git", *GIT_ID, "add", "-A"], cwd=dest, check=True)
    subprocess.run(
        ["git", *GIT_ID, "commit", "-q", "--no-verify", "-m", "base"], cwd=dest, check=True
    )
    return Workspace(dest, repo_id=cfg.get("repo_id") or f"local:{src.name}", cfg=cfg)
