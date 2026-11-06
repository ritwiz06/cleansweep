"""`clean --sandbox docker`: the project's code runs only in a python:3.11 container.

The mechanics are the AIDev workspace's: the workspace folder stays on the host (the agents'
static tools only parse its files) and is mounted at /repo; the container installs the project
with network access, then is cut off from the network before any of the project's own code
runs (tests, imports, probes). Removing the container leaves the workspace folder, which holds
the delivered branch.

`auto` picks the sandbox: none (this machine) for a folder in a git repository you own, docker
for anything else. Owned means the repository has at least one commit whose author email is
your `git config --global user.email` (not the repository's own setting, which its owner
chose); a plain folder, a repository with no commits, or no user.email set count as not
owned."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

from .aidev_docker import IMAGE, JUNIT, MOUNT, AidevWorkspace, _docker
from .workspace import UNITTEST_PY

SANDBOXES = ("auto", "docker", "none")
PREFIX = "cs-clean-"
OWNER_LABEL = "cleansweep.owner"  # the pid of the run that started the container
INSTALL_TIMEOUT = 900
TOOLS = [["pip", "install", "pytest", "coverage"]]  # the test runner and the probes' coverage


class SandboxError(RuntimeError):
    """The sandbox cannot be set up: Docker is missing or not running, or the network stays on."""


def _git(path: Path, *args: str) -> str | None:
    proc = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def owner(path: str | Path) -> tuple[bool, str]:
    """(is the folder in a git repository you own, why)."""
    path = Path(path)
    if not path.is_dir() or _git(path, "rev-parse", "--show-toplevel") is None:
        return False, "not a git repository"
    # your own setting, not the repository's: its .git/config could name its authors
    email = _git(Path.home(), "config", "--global", "user.email")
    if not email:
        return False, "a git repository, but your git config has no user.email to compare with"
    authors = (_git(path, "log", "--format=%ae") or "").lower().split()
    if email.lower() not in authors:
        return False, f"a git repository with no commit by you ({email})"
    return True, f"a git repository with commits by you ({email})"


def choose(path: str | Path, setting: str = "auto", untrusted: bool = False) -> tuple[str, str]:
    """("docker" or "none", why) for a project folder."""
    if setting not in SANDBOXES:
        raise ValueError(f"sandbox must be one of {', '.join(SANDBOXES)}, got {setting!r}")
    if untrusted:
        return "docker", "--untrusted"
    if setting != "auto":
        return setting, f"--sandbox {setting}"
    mine, why = owner(path)
    return ("none" if mine else "docker"), why


def check_docker() -> None:
    """Raise SandboxError unless the docker command works and its daemon answers."""
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise SandboxError("Docker is not installed; install it, or use --sandbox none") from None
    except subprocess.TimeoutExpired:
        proc = None
    if proc is None or proc.returncode != 0:
        raise SandboxError(
            "Docker is not running; start it, or use --sandbox none for a project you trust"
        )


class ContainerWorkspace(AidevWorkspace):
    """A `clean` workspace whose commands run in a network-less python:3.11 container."""

    install_info = ""

    def run_tests(self, test_paths: list[str] | None = None, timeout: int = 900):
        """The project's test command in the container (see Workspace.run_tests)."""
        runner = self.test_command.get("runner", "pytest")
        if runner == "command":
            self.test_runs += 1
            return self._run_command(timeout)
        if runner == "unittest":
            cmd = ["python", "-c", UNITTEST_PY, JUNIT, *self._unittest_args(test_paths)]
        else:
            cmd = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={JUNIT}"]
            cmd += ["--continue-on-collection-errors", *self.pytest_args]
            cmd += test_paths or self.test_command.get("paths", [])
        return self._junit_run(cmd, timeout)

    def install(self, steps: list[list[str]]) -> str:
        """Run pip install steps ("pip install ...") while the network is on; a line for the
        report."""
        failed = None
        for step in steps:
            failed = self._pip(step)
            if failed:
                break
        failed = failed or self._pip(*TOOLS)
        shown = " && ".join(shlex.join(s) for s in steps) or "nothing to install"
        what = (
            f"install failed in the container ({failed})"
            if failed
            else "installed in the container"
        )
        return f"{what} ({shown}); network off after the install"

    def _pip(self, step: list[str]) -> str | None:
        argv = ["python", "-m", "pip", "install", "-q", *step[2:]]
        code, out = self._exec(shlex.join(argv), INSTALL_TIMEOUT)
        if code == 0:
            return None
        last = out.strip().splitlines()[-1][:200] if out.strip() else f"exit {code}"
        return f"{shlex.join(step)}: {last}"

    def close(self) -> None:
        """Remove the container; the workspace folder stays."""
        _docker(["rm", "-f", self.container])


def open_container(
    path: str | Path, repo_id: str, cfg: dict | None, install: list[list[str]]
) -> ContainerWorkspace:
    """Start a container on a workspace folder, run the install steps, then cut the network."""
    cfg = cfg or {}
    check_docker()
    path = Path(path).resolve()
    stamp = hashlib.sha1(f"{path}{time.time_ns()}".encode()).hexdigest()[:8]
    name = re.sub(r"[^a-zA-Z0-9_.-]", "-", f"{PREFIX}{path.parent.name}-{stamp}").lower()
    env = ["--label", f"{OWNER_LABEL}={os.getpid()}", "-e", "PYTHONDONTWRITEBYTECODE=1"]
    if (path / "src").is_dir():
        env += ["-e", f"PYTHONPATH={MOUNT}/src"]
    run = ["run", "-d", "--name", name, *env, "-v", f"{path}:{MOUNT}", "-w", MOUNT]
    image = cfg.get("clean_image", IMAGE)
    proc = _docker([*run, image, "sleep", "infinity"], timeout=900)
    if proc.returncode != 0:
        _docker(["rm", "-f", name])
        raise SandboxError(f"could not start the {image} container: {proc.stderr.strip()[-300:]}")
    ws = ContainerWorkspace(path, repo_id, cfg, name)
    ws.install_info = ws.install(install)
    cut = _docker(["network", "disconnect", "bridge", name])
    if cut.returncode != 0:
        ws.close()
        raise SandboxError(f"could not turn the container's network off: {cut.stderr.strip()}")
    return ws
