"""Scratch goes when a run ends, however it ends; a runner's start removes what killed runs left."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .container import OWNER_LABEL, PREFIX
from .local import default_work_dir
from .workspace import OWNER_FILE

# the temp folders the code makes outside a workspace (probe harness, experiment scripts)
TEMP_PREFIXES = ("cs_probe_", "cs_cov_", "cs_fork_", "cs_inject_", "cs_confirm_", "cs_fresh_")
DAY = 24 * 3600


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _owned(path: Path) -> bool:
    try:
        return _alive(int((path / ".git" / OWNER_FILE).read_text()))
    except (OSError, ValueError):
        return False


def _orphans(root: Path, prefixes: tuple[str, ...] | None, max_age_s: float) -> list[Path]:
    if not root.is_dir():
        return []
    now = time.time()
    out = []
    for path in sorted(root.iterdir()):
        if prefixes is not None and not path.name.startswith(prefixes):
            continue
        if prefixes is None and not (path / ".git").is_dir():
            continue  # an agent run folder without a repository holds events and logs
        try:
            old = now - path.stat().st_mtime >= max_age_s
        except OSError:
            continue
        if path.is_dir() and old and not _owned(path):
            out.append(path)
    return out


def sweep_orphans(sandbox: dict | None = None, max_age_s: float = DAY) -> list[str]:
    """Remove workspaces and temp folders older than max_age_s that no live process owns, with
    their containers; return the removed paths."""
    found = _orphans(default_work_dir(sandbox or {}), None, max_age_s)
    found += _orphans(Path(tempfile.gettempdir()), TEMP_PREFIXES, max_age_s)
    docker = shutil.which("docker")
    for path in found:
        if docker and path.name.startswith("cs-"):  # a Docker workspace's container has its name
            try:
                subprocess.run([docker, "rm", "-f", path.name], capture_output=True, timeout=60)
            except subprocess.TimeoutExpired:
                pass
        shutil.rmtree(path, ignore_errors=True)
    return [str(p) for p in found]


def sweep_containers() -> list[str]:
    """Remove `clean --sandbox docker` containers whose run is no longer alive (a killed run
    cannot remove its own); return their names."""
    docker = shutil.which("docker")
    if not docker:
        return []
    fmt = f'{{{{.Names}}}} {{{{.Label "{OWNER_LABEL}"}}}}'
    try:
        proc = subprocess.run(
            [docker, "ps", "-a", "--filter", f"name=^{PREFIX}", "--format", fmt],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return []
    stale = []
    for line in proc.stdout.splitlines() if proc.returncode == 0 else []:
        name, _, pid = line.partition(" ")
        if name.startswith(PREFIX) and not (pid.isdigit() and _alive(int(pid))):
            stale.append(name)
    for name in stale:
        try:
            subprocess.run([docker, "rm", "-f", name], capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            pass
    return stale


def _exit(signum, frame) -> None:
    raise SystemExit(128 + signum)


def exit_on_signals() -> None:
    """Turn SIGTERM and SIGHUP into SystemExit, so finally blocks remove scratch; a signal that is
    already ignored (nohup) stays ignored."""
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            if signal.getsignal(sig) == signal.SIG_DFL:
                signal.signal(sig, _exit)
        except ValueError:  # not the main thread
            return


def on_start(sandbox: dict | None = None) -> list[str]:
    """A runner's start: clean up on signals from here on, and sweep earlier runs' orphans."""
    exit_on_signals()
    return sweep_orphans(sandbox) + sweep_containers()
