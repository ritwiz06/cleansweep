"""Scratch workspace for `clean` and the delivered branch. The original folder is only read."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from cleansweep.sandbox.local import SKIP, WS_EXCLUDE
from cleansweep.sandbox.workspace import GIT_ID, Workspace

EXCLUDE = WS_EXCLUDE + ["_cs_*/"]


def _git(cwd: str | Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", *GIT_ID, *args], cwd=cwd, capture_output=True, text=True, env=env, check=check
    )


def is_git_repo(path: Path) -> bool:
    proc = _git(path, "rev-parse", "--show-toplevel", check=False)
    return proc.returncode == 0 and Path(proc.stdout.strip()).resolve() == path.resolve()


def inside(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def default_out(src: Path) -> Path:
    """Next to the project, never inside it: <parent>/<name>-cleanup-<timestamp>."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return src.resolve().parent / f"{src.resolve().name}-cleanup-{stamp}"


def prepare_workspace(
    src: str | Path, dest: str | Path, cfg: dict | None = None
) -> tuple[Workspace, dict]:
    """Copy the project into `dest` as a git repo whose HEAD is the starting point.

    A git repository is cloned (the branch then applies to its history); uncommitted changes in
    its working tree are copied in and committed on top, so the cleanup starts from what the
    user sees. A plain folder is copied and committed as "base"."""
    src, dest = Path(src).resolve(), Path(dest)
    if not src.is_dir():
        raise FileNotFoundError(f"no such folder: {src}")
    info: dict = {"source": str(src)}
    if is_git_repo(src):
        _git(dest.parent, "clone", "--quiet", "--no-hardlinks", str(src), str(dest))
        head = _git(src, "rev-parse", "HEAD").stdout.strip()
        branch = _git(src, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        info.update(kind="git clone", head=head, branch=branch)
        status = _git(src, "status", "--porcelain").stdout
        if status.strip():
            _copy_working_tree(src, dest)
            _git(dest, "add", "-A")
            _git(
                dest,
                "commit",
                "-q",
                "--no-verify",
                "-m",
                "Uncommitted changes from the original folder",
            )
            info["uncommitted_changes"] = True
    else:
        shutil.copytree(src, dest, ignore=SKIP)
        _git(dest, "init", "-q")
        _write_exclude(dest)
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "--no-verify", "-m", "base")
        info.update(
            kind="copy", branch=_git(dest, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        )
    _write_exclude(dest)
    info["base"] = _git(dest, "rev-parse", "HEAD").stdout.strip()
    ws = Workspace(dest, repo_id=f"local:{src.name}", cfg=cfg or {})
    return ws, info


def _write_exclude(dest: Path) -> None:
    path = dest / ".git" / "info" / "exclude"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text() if path.exists() else ""
    path.write_text(old + "\n".join(p for p in EXCLUDE if p not in old) + "\n")


def _copy_working_tree(src: Path, dest: Path) -> None:
    """Mirror the original's tracked and untracked (not ignored) files into the clone."""
    listed = _git(src, "ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
    files = {f for f in listed.split("\0") if f}
    for rel in files:
        source = src / rel
        if source.is_file():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    tracked = _git(dest, "ls-files", "-z").stdout
    for rel in filter(None, tracked.split("\0")):
        if not (src / rel).exists():
            (dest / rel).unlink(missing_ok=True)


def finish(rt, info: dict, patches: bool = True) -> dict:
    """Name the delivery branch, leave the workspace on it, reset the scratch branch, and write
    the patch series. Returns where things are."""
    ws, out = rt.ws, rt.out
    result = {"workspace": ws.path, "base": ws.base, "branch": None, "commits": 0, "patches": None}
    if rt.delivery_tip is None:
        return result
    name = f"cleansweep/cleanup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    _git(ws.path, "update-ref", f"refs/heads/{name}", rt.delivery_tip)
    _git(ws.path, "checkout", "-q", "-f", name)
    _git(ws.path, "clean", "-q", "-fd")
    scratch = info.get("branch")
    if scratch and scratch not in ("HEAD", name):
        _git(ws.path, "branch", "-f", scratch, ws.base, check=False)
    count = int(_git(ws.path, "rev-list", "--count", f"{ws.base}..{name}").stdout.strip() or 0)
    result.update(branch=name, commits=count)
    if patches:
        folder = out / "patches"
        _git(ws.path, "format-patch", "-q", f"{ws.base}..{name}", "-o", str(folder))
        result["patches"] = str(folder)
    rt.branch = name
    return result
