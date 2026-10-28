"""SWE-bench targets: the code lives in a local git mirror, and commands run in the instance's
prebuilt container.

The mirror has two commits, `base` (the project with the SWE-bench test patch) and `agent patch`
(the agent's change). Static tools read the mirror. Before every command the container is reset
to the same two commits and given the mirror's current diff, so it always runs what the mirror
holds. The test command, its directive format, the setup lines and the log parser all come from
the instance's swebench data; nothing here is specific to one repository.
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
from .workspace import GIT_ID, Workspace

PLATFORM = "linux/amd64"  # SWE-bench images are x86_64; Docker emulates them on arm64
TESTBED = "/testbed"
ACTIVATE = "source /opt/miniconda3/bin/activate && conda activate testbed"
START, END = ">>>>> Start Test Output", ">>>>> End Test Output"
GIT = "git " + " ".join(GIT_ID)
PROBE_DIR = "_probes"


def _docker(args: list[str], timeout: float | None = None, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, **kw)


def patch_files(patch: str) -> list[str]:
    """Paths a unified diff touches (the b/ side; deleted files keep their a/ path)."""
    files = []
    for m in re.finditer(r"^diff --git a/(\S+) b/(\S+)$", patch, re.MULTILINE):
        files.append(m.group(2))
    return files


def drop_files(patch: str, paths: set[str]) -> str:
    """The patch without the file sections for `paths`."""
    sections = re.split(r"(?m)^(?=diff --git )", patch)
    keep = [s for s in sections if not any(s.startswith(f"diff --git a/{p} ") for p in paths)]
    return "".join(keep)


def eval_lines(eval_script: str) -> tuple[list[str], str]:
    """(setup lines worth repeating before a test run, the test command line)."""
    lines = eval_script.splitlines()
    try:
        i = next(k for k, line in enumerate(lines) if START in line)
    except StopIteration:
        return [], ""
    setup = []
    for line in lines[:i]:
        s = line.strip()
        if s.startswith("git apply") or "<<'EOF" in s:
            break  # the test patch follows; it is already in the base commit
        if not s or s.startswith(("#", "set ", "cd ", "git ", "source ", "conda activate")):
            continue
        setup.append(s)
    return setup, lines[i + 1].strip() if i + 1 < len(lines) else ""


INSTALL = re.compile(r"\bpip install\b|\bsetup\.py (install|develop)\b")


def directive_style(command: str, test_files: list[str]):
    """How this instance's command names test files, learned from its own directives."""
    tokens = set(shlex.split(command))

    def as_path(f: str) -> str:
        return f

    def no_ext(f: str) -> str:
        return f[:-3] if f.endswith(".py") else f

    def dotted(f: str) -> str:
        return no_ext(f).replace("/", ".")

    def dotted_tail(f: str) -> str:
        return dotted(f.split("/", 1)[1]) if "/" in f else dotted(f)

    for style in (as_path, no_ext, dotted_tail, dotted):
        if any(style(f) in tokens for f in test_files):
            return style
    return as_path


def command_for(command: str, test_files: list[str], test_paths: list[str] | None) -> str:
    """The test command with its directives replaced by test_paths (None keeps them)."""
    if test_paths is None:
        return command
    style = directive_style(command, test_files)
    tokens = shlex.split(command)
    directives = {style(f) for f in test_files}
    cut = next((k for k, t in enumerate(tokens) if t in directives), len(tokens))
    return shlex.join([*tokens[:cut], *(style(p) for p in test_paths)])


def to_result(status: dict[str, str], flaky: set[str], seconds: float) -> RunResult:
    """A RunResult from a swebench status map, ignoring tests known to be flaky."""
    if not status:
        return RunResult(ok=False, errors=1, failed_ids=["<no test results>"], duration_s=seconds)
    result = RunResult(ok=True, duration_s=seconds)
    for test, state in sorted(status.items()):
        if test in flaky:
            continue
        if state in ("PASSED", "XFAIL"):
            result.passed += 1
        elif state == "SKIPPED":
            result.skipped += 1
        elif state == "ERROR":
            result.errors += 1
            result.failed_ids.append(test)
        else:
            result.failed += 1
            result.failed_ids.append(test)
    result.ok = not result.failed_ids
    return result


class SwebenchWorkspace(Workspace):
    """A local mirror of /testbed whose commands run inside the instance's container."""

    python = "python"  # the container's interpreter (the testbed conda env)
    probe_runner = True

    def __init__(self, path, repo_id: str, cfg: dict, container: str, row: dict, head: str):
        super().__init__(path, repo_id, cfg)
        from swebench.harness.log_parsers import PARSER_REGISTRY
        from swebench.harness.utils import make_test_spec

        self.container = container
        self.row = row
        self.spec = make_test_spec(row)
        self.parser = PARSER_REGISTRY[row["log_parser"]]
        self.container_head = head  # the container's "agent patch" commit
        self.test_files = [f for f in patch_files(row["test_patch"]) if f.endswith(".py")]
        self.setup, self.command = eval_lines(row["eval_script"])
        self.flaky: set[str] = set()
        self._synced: str | None = None

    def _exec(self, script: str, timeout: float) -> tuple[int, str]:
        wrapped = f"{ACTIVATE} && cd {TESTBED} && {script}"
        args = ["exec", self.container, "timeout", "-s", "KILL", str(int(timeout))]
        try:
            proc = _docker([*args, "bash", "-c", wrapped], timeout=timeout + 60)
        except subprocess.TimeoutExpired:
            return 124, f"timeout after {timeout}s"
        code = 124 if proc.returncode == 137 else proc.returncode
        return code, proc.stdout + proc.stderr

    def sync(self) -> None:
        """Make the container's /testbed match the mirror (deleted files included)."""
        diff = self.diff(self.base)
        probes = Path(self.path) / PROBE_DIR
        stamp = sorted(str(p) for p in probes.rglob("*")) if probes.exists() else []
        key = hashlib.sha256((diff + "\n".join(stamp)).encode()).hexdigest()
        if key == self._synced:
            return
        code, out = self._exec(
            f"{GIT} reset -q --hard {self.container_head} && git clean -q -fd", 300
        )
        if code != 0:
            raise RuntimeError(f"container reset failed: {out[-500:]}")
        if diff:
            with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
                f.write(diff if diff.endswith("\n") else diff + "\n")
            _docker(["cp", f.name, f"{self.container}:/tmp/cs_sync.diff"], check=True)
            Path(f.name).unlink(missing_ok=True)
            code, out = self._exec("git apply --binary /tmp/cs_sync.diff", 300)
            if code != 0:
                # e.g. CRLF files the mirror's git normalized: copy the files over instead
                self._copy_changes(out)
        if probes.exists():
            _docker(["cp", str(probes), f"{self.container}:{TESTBED}/"], check=True)
        self._synced = key

    def _copy_changes(self, apply_error: str) -> None:
        """Make the container's files match the mirror's changes file by file."""
        self._git("add", "-A")
        status = self._git("diff", "--cached", "--name-status", "--no-renames", self.base)
        self._git("reset", "-q")
        for line in status.splitlines():
            state, path = line.split("\t", 1)
            target = f"{self.container}:{TESTBED}/{path}"
            if state == "D":
                code, out = self._exec(f"rm -f {shlex.quote(path)}", 60)
            else:
                self._exec(f"mkdir -p {shlex.quote(str(Path(path).parent))}", 60)
                proc = _docker(["cp", str(Path(self.path) / path), target])
                code, out = proc.returncode, proc.stderr
            if code != 0:
                raise RuntimeError(f"container sync failed: {apply_error[-300:]} / {out[-200:]}")

    def fetch(self, rel_path: str) -> None:
        """Copy a file the container wrote under /testbed back into the mirror."""
        dest = Path(self.path) / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        _docker(["cp", f"{self.container}:{TESTBED}/{rel_path}", str(dest)])

    def run(self, cmd: list[str], timeout: int = 300) -> tuple[int, str]:
        """Run a command in the container's /testbed (the host Python maps to the testbed's)."""
        self.sync()
        if cmd and cmd[0] == sys.executable:
            cmd = [self.python, *cmd[1:]]
        return self._exec(shlex.join(cmd), timeout)

    def run_tests(self, test_paths: list[str] | None = None, timeout: int = 900) -> RunResult:
        """Run the instance's test command (or test_paths) and parse it with its log parser."""
        self.test_runs += 1
        self.sync()
        command = command_for(self.command, self.test_files, test_paths)
        script = "\n".join([*self.setup, f": '{START}'", command, f": '{END}'"])
        start = time.time()
        code, out = self._exec(script, timeout or self.cfg.get("test_timeout_s", 900))
        self.last_test_output = out
        section = out.split(START, 1)[-1].split(END, 1)[0]
        status = self.parser(section, self.spec) or self.parser(out, self.spec)
        return to_result(status, self.flaky, time.time() - start)

    def find_flaky(self, runs: int = 3) -> set[str]:
        """Run the baseline tests several times; tests whose status changes are flaky."""
        seen: dict[str, set[str]] = {}
        for _ in range(runs):
            self.test_runs += 1
            self.sync()
            script = "\n".join([*self.setup, f": '{START}'", self.command, f": '{END}'"])
            _, out = self._exec(script, self.cfg.get("test_timeout_s", 900))
            section = out.split(START, 1)[-1].split(END, 1)[0]
            for test, state in (self.parser(section, self.spec) or {}).items():
                seen.setdefault(test, set()).add(state)
        self.flaky = {t for t, states in seen.items() if len(states) > 1}
        return self.flaky

    def skip_reinstall_if_editable(self) -> None:
        """Drop install lines from the per-run setup when /testbed is installed in editable
        mode: edits are live without them, and reinstalling costs seconds per test run."""
        code, out = self._exec("python -m pip list --editable --format=json", 120)
        try:
            editable = json.loads(out[out.index("[") : out.rindex("]") + 1]) if code == 0 else []
        except ValueError:
            editable = []
        if any(p.get("editable_project_location") == TESTBED for p in editable):
            self.setup = [line for line in self.setup if not INSTALL.search(line)]

    def probe_test_dir(self) -> str | None:
        """The folder of the instance's first test file: its test command collects files there
        with the same setup (Django test app, conftest.py files on the way)."""
        return str(Path(self.test_files[0]).parent) if self.test_files else None

    def run_probe_test(
        self, rel_path: str, timeout: int = 900, with_directives: bool = True
    ) -> tuple[int, str]:
        """The instance's test command on the generated file (plus its own directives, so the
        test setup is the one its tests get). The file is git-excluded, so it is copied in."""
        self.sync()
        _docker(["cp", str(Path(self.path) / rel_path), f"{self.container}:{TESTBED}/{rel_path}"])
        paths = [*self.test_files, rel_path] if with_directives else [rel_path]
        command = command_for(self.command, self.test_files, paths)
        script = "\n".join([*self.setup, command])
        try:
            return self._exec(script, timeout)
        finally:
            self._exec(f"rm -f {shlex.quote(rel_path)}", 60)

    def coverage_json(self, test_paths: list[str] | None = None) -> str | None:
        return None  # not collected inside containers

    def fork(self) -> Workspace:
        raise NotImplementedError("open a second SWE-bench workspace instead of forking")

    def close(self) -> None:
        """Remove the container and the mirror."""
        _docker(["rm", "-f", self.container])
        shutil.rmtree(self.path, ignore_errors=True)


def _apply_in_container(container: str, patch: str, label: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
        f.write(patch if patch.endswith("\n") else patch + "\n")
    _docker(["cp", f.name, f"{container}:/tmp/cs_{label}.diff"], check=True)
    Path(f.name).unlink(missing_ok=True)
    script = (
        f"cd {TESTBED} && (git apply /tmp/cs_{label}.diff || "
        f"patch --batch --fuzz=5 -p1 -i /tmp/cs_{label}.diff)"
    )
    proc = _docker(["exec", container, "bash", "-c", script])
    if proc.returncode != 0:
        raise RuntimeError(f"{label} does not apply in the container: {proc.stderr[-500:]}")


def _commit_in_container(container: str, message: str) -> str:
    commit = f"{GIT} commit -q --allow-empty -m '{message}'"
    script = f"cd {TESTBED} && git add -A && {commit} && git rev-parse HEAD"
    proc = _docker(["exec", container, "bash", "-c", script])
    if proc.returncode != 0:
        raise RuntimeError(f"commit in container failed: {proc.stderr[-500:]}")
    return proc.stdout.strip().splitlines()[-1]


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *GIT_ID, *args], cwd=path, check=True, capture_output=True)


def open_swebench(target: str, cfg: dict | None = None) -> SwebenchWorkspace:
    """Open "swebench:<instance_id>:<agent>": start the container, build the mirror."""
    from cleansweep.data import load_agent_patches
    from cleansweep.data.swebench import load_rows

    cfg = cfg or {}
    _, instance_id, agent = target.split(":", 2)
    rows = load_rows([instance_id])
    if not rows:
        raise ValueError(f"unknown SWE-bench instance {instance_id}")
    row = rows[0]
    found = [p for p in load_agent_patches([agent]) if p.instance_id == instance_id]
    if not found:
        raise ValueError(f"no plausible {agent} patch for {instance_id}")
    test_files = set(patch_files(row["test_patch"]))
    agent_patch = drop_files(found[0].patch, test_files)  # SWE-bench resets these files too

    stamp = hashlib.sha1(f"{target}{time.time_ns()}".encode()).hexdigest()[:8]
    name = re.sub(r"[^a-zA-Z0-9_.-]", "-", f"cs-{instance_id}-{agent}-{stamp}").lower()
    run = ["run", "-d", "--platform", cfg.get("platform", PLATFORM), "--name", name]
    proc = _docker([*run, row["image"], "sleep", "infinity"])
    if proc.returncode != 0:
        raise RuntimeError(f"could not start {row['image']}: {proc.stderr.strip()[-300:]}")
    try:
        _apply_in_container(name, row["test_patch"], "test_patch")
        base_in_container = _commit_in_container(name, "base")
        dest = default_work_dir(cfg) / name
        dest.mkdir(parents=True)
        tar = subprocess.Popen(
            ["docker", "exec", name, "tar", "-C", TESTBED, "--exclude=./.git", "-cf", "-", "."],
            stdout=subprocess.PIPE,
        )
        subprocess.run(["tar", "-xf", "-", "-C", str(dest)], stdin=tar.stdout, check=True)
        tar.wait()
        subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
        (dest / ".git" / "info" / "exclude").write_text("\n".join(WS_EXCLUDE) + "\n")
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "--no-verify", "-m", "base")
        _apply_in_container(name, agent_patch, "agent_patch")
        head = _commit_in_container(name, "agent patch")
        ws = SwebenchWorkspace(dest, target, cfg, name, row, head)
        # the container may have needed `patch --fuzz`; give the mirror the exact result
        applied = _docker(
            [
                "exec",
                name,
                "bash",
                "-c",
                f"cd {TESTBED} && git diff --binary {base_in_container} HEAD",
            ]
        )
        if applied.returncode != 0 or not ws.apply_patch(applied.stdout):
            raise RuntimeError("the agent patch does not apply to the mirror")
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "--no-verify", "-m", "agent patch")
        ws.base = ws._git("rev-parse", "HEAD").strip()
        ws._synced = None
        ws.skip_reinstall_if_editable()
        if cfg.get("flaky_runs", 3) > 0:
            ws.find_flaky(cfg.get("flaky_runs", 3))
        return ws
    except Exception:
        _docker(["rm", "-f", name])
        raise
