"""AIDev targets: an untrusted GitHub repository, run only inside a python:3.11 container.

The workspace folder (a git repo with a `base` commit, like a local workspace) is mounted at
/repo, so edits on the host are visible in the container at once. The container installs the
project with network access, then is cut off from the network before any of the project's
own code runs (tests, imports, probes). Static tools on the host only parse files.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from cleansweep.core.models import RunResult

from .local import WS_EXCLUDE, default_work_dir
from .workspace import GIT_ID, Workspace, junit_statuses, parse_junit

IMAGE = "python:3.11"
MOUNT = "/repo"
# Runs inside the container (python:3.11): install the project with whatever test/dev extras
# and dependency groups it declares, its requirements files, then pytest.
INSTALL_PY = r"""
import glob, os, subprocess, sys, tomllib
def pip(*args):
    return subprocess.run([sys.executable, "-m", "pip", "install", "-q", *args]).returncode
pip("--upgrade", "pip")
wanted = ("test", "tests", "testing", "dev", "develop")
ok = True
if os.path.exists("pyproject.toml") or os.path.exists("setup.py"):
    data = {}
    if os.path.exists("pyproject.toml"):
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
    extras = [e for e in data.get("project", {}).get("optional-dependencies", {}) if e in wanted]
    target = ".[" + ",".join(extras) + "]" if extras else "."
    ok = pip("-e", target) == 0 or pip("-e", ".") == 0
    for group in data.get("dependency-groups", {}):
        if group in wanted:
            pip("--group", group)
for f in sorted(set(glob.glob("requirements*.txt") + glob.glob("*requirements*.txt")
                    + glob.glob("requirements/*.txt"))):
    if any(w in f for w in ("dev", "test", "requirements.txt")):
        pip("-r", f)
pip("pytest", "coverage")
sys.exit(0 if ok else 1)
"""
INSTALL = "python - <<'CS_EOF'\n" + INSTALL_PY + "\nCS_EOF"


def _docker(args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return subprocess.CompletedProcess(exc.cmd, 124, out, f"timeout after {timeout}s")


class AidevWorkspace(Workspace):
    """A git workspace whose commands run in a network-less python:3.11 container."""

    python = "python"
    probe_runner = True

    def __init__(self, path, repo_id: str, cfg: dict, container: str):
        super().__init__(path, repo_id, cfg)
        self.container = container
        self.install_log = ""

    def _exec(self, cmd: str, timeout: float) -> tuple[int, str]:
        args = ["exec", "-w", MOUNT, self.container, "timeout", "-s", "KILL", str(int(timeout))]
        proc = _docker([*args, "bash", "-c", cmd], timeout=timeout + 60)
        code = 124 if proc.returncode == 137 else proc.returncode
        return code, proc.stdout + proc.stderr

    def install(self, timeout: int = 600) -> bool:
        """Install the project and pytest (with network), then disconnect the network."""
        code, out = self._exec(INSTALL, timeout)
        self.install_log = out[-4000:]
        _docker(["network", "disconnect", "bridge", self.container])
        return code == 0

    def run(self, cmd: list[str], timeout: int = 300) -> tuple[int, str]:
        """Run a command in the container (the host Python maps to the container's)."""
        if cmd and cmd[0] == sys.executable:
            cmd = [self.python, *cmd[1:]]
        return self._exec(shlex.join(cmd), timeout)

    def run_tests(self, test_paths: list[str] | None = None, timeout: int = 900) -> RunResult:
        """pytest in the container with a JUnit report copied back to the host."""
        self.test_runs += 1
        xml = "/tmp/cs_junit.xml"
        # an optional dependency missing in one module must not stop the whole run
        cmd = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}"]
        cmd.append("--continue-on-collection-errors")
        start = time.time()
        code, out = self._exec(shlex.join([*cmd, *(test_paths or [])]), timeout)
        self.last_test_output = out
        self.last_statuses = {}
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "junit.xml"
            _docker(["cp", f"{self.container}:{xml}", str(local)])
            _docker(["exec", self.container, "rm", "-f", xml])
            if not local.exists():
                failed = "<timeout>" if code == 124 else f"<pytest exit {code}>"
                return RunResult(
                    ok=False, errors=1, failed_ids=[failed], duration_s=time.time() - start
                )
            result = parse_junit(local, time.time() - start)
            self.last_statuses = junit_statuses(local)
        if code not in (0, 1, 5) and result.ok:
            result.ok, result.errors = False, result.errors + 1
        return result

    def probe_test_dir(self) -> str | None:
        for name in ("tests", "test"):
            if (Path(self.path) / name).is_dir():
                return name
        return "."

    def run_probe_test(
        self, rel_path: str, timeout: int = 900, with_directives: bool = True
    ) -> tuple[int, str]:
        """pytest on the generated file only (conftest.py files on its path load); a whole
        AIDev suite can take minutes, so its tests are not added."""
        cmd = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", rel_path]
        return self._exec(shlex.join(cmd), timeout)

    def coverage_json(self, test_paths: list[str] | None = None) -> str | None:
        return None  # not collected for AIDev repositories

    def fork(self) -> Workspace:
        raise NotImplementedError("open a second AIDev workspace instead of forking")

    def close(self) -> None:
        _docker(["rm", "-f", self.container])
        shutil.rmtree(self.path, ignore_errors=True)


def write_scope(dest: Path, clone: str, full_name: str, sha: str) -> bool:
    """Store what agent pull requests wrote (blame on the clone's history) in dest/.git, where
    analysis.scope.agent_scope finds it. False when the repository has no cached history."""
    from cleansweep.analysis.scope import SCOPE_FILE, blame_scope
    from cleansweep.data.aidev import agent_history

    try:
        shas, start = agent_history(full_name, sha)
    except (OSError, KeyError, ValueError):
        return False
    if not shas:
        return False
    scope = blame_scope(clone, sha, shas, start)
    (dest / ".git" / SCOPE_FILE).write_text(json.dumps(scope))
    return True


def clone_dir(cfg: dict, full_name: str) -> Path:
    from cleansweep.data.swebench import data_path

    root = data_path(cfg.get("aidev_clones", "data/raw/aidev/repos"))
    return root / full_name.replace("/", "__")


def open_aidev(target: str, cfg: dict | None = None) -> AidevWorkspace:
    """Open "aidev:<owner>/<name>@<sha>" from its blobless clone (made by
    scripts/data_aidev_select.py): copy the tree at sha, start the container, install."""
    cfg = cfg or {}
    spec = target.removeprefix("aidev:")
    full_name, _, sha = spec.partition("@")
    clone = clone_dir(cfg, full_name)
    if not (clone / ".git").exists():
        raise FileNotFoundError(f"no clone for {full_name} in {clone}; run data_aidev_select.py")
    stamp = hashlib.sha1(f"{target}{time.time_ns()}".encode()).hexdigest()[:8]
    name = re.sub(r"[^a-zA-Z0-9_.-]", "-", f"cs-aidev-{full_name}-{stamp}").lower()
    dest = default_work_dir(cfg) / name
    dest.mkdir(parents=True)
    archive = subprocess.Popen(
        ["git", "archive", "--format=tar", sha or "HEAD"], cwd=clone, stdout=subprocess.PIPE
    )
    subprocess.run(["tar", "-xf", "-", "-C", str(dest)], stdin=archive.stdout, check=True)
    if archive.wait() != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError(f"git archive failed for {target}")
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    (dest / ".git" / "info" / "exclude").write_text("\n".join(WS_EXCLUDE) + "\n")
    subprocess.run(["git", *GIT_ID, "add", "-A"], cwd=dest, check=True)
    subprocess.run(
        ["git", *GIT_ID, "commit", "-q", "--no-verify", "-m", "base"], cwd=dest, check=True
    )
    if cfg.get("agent_scope", True):
        write_scope(dest, str(clone), full_name, sha or "HEAD")
    run = ["run", "-d", "--name", name, "-v", f"{dest}:{MOUNT}", "-w", MOUNT]
    proc = _docker([*run, cfg.get("aidev_image", IMAGE), "sleep", "infinity"], timeout=300)
    if proc.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError(f"could not start {IMAGE}: {proc.stderr.strip()[-300:]}")
    ws = AidevWorkspace(dest, target, cfg, name)
    if cfg.get("install", True) and not ws.install(int(cfg.get("install_timeout_s", 600))):
        ws.close()
        raise RuntimeError(f"install failed for {target}: {ws.install_log[-300:]}")
    return ws
