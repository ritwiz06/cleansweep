from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from cleansweep.core.models import RunResult

GIT_ID = [
    "-c",
    "user.name=cleansweep",
    "-c",
    "user.email=cleansweep@localhost",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "gc.auto=0",  # no background repacking in throwaway workspaces
]


def parse_junit(xml_path: str | Path, duration_s: float = 0.0) -> RunResult:
    """Read a pytest JUnit XML file into a RunResult."""
    root = ET.parse(xml_path).getroot()
    result = RunResult(ok=True, duration_s=duration_s)
    for case in root.iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        tags = {child.tag for child in case}
        if "failure" in tags:
            result.failed += 1
            result.failed_ids.append(test_id)
        elif "error" in tags:
            result.errors += 1
            result.failed_ids.append(test_id)
        elif "skipped" in tags:
            result.skipped += 1
        else:
            result.passed += 1
    for suite in root.iter("testsuite"):
        # collection errors show up as suite-level errors with no testcase
        extra = int(suite.get("errors", 0)) - sum(
            1 for c in suite.iter("testcase") if any(ch.tag == "error" for ch in c)
        )
        result.errors += max(extra, 0)
    result.ok = result.failed == 0 and result.errors == 0
    return result


class Workspace:
    """A scratch git repo holding the code under cleanup. Every edit can be rolled back."""

    def __init__(self, path: str | Path, repo_id: str, cfg: dict | None = None):
        self.path = str(path)
        self.repo_id = repo_id
        self.cfg = cfg or {}
        self.test_runs = 0
        self.base = self._git("rev-parse", "HEAD").strip()
        qdir = Path(self.cfg.get("quarantine_dir") or ".cleansweep/quarantine")
        self.quarantine_dir = str(qdir.resolve() / repo_id.replace("/", "_").replace(":", "_"))

    def _git(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", *GIT_ID, *args], cwd=self.path, capture_output=True, text=True
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {proc.stderr.strip()}")
        return proc.stdout

    def run(self, cmd: list[str], timeout: int = 300) -> tuple[int, str]:
        """Run a command inside the workspace; return (exit code, stdout+stderr)."""
        try:
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            proc = subprocess.run(
                cmd, cwd=self.path, capture_output=True, text=True, timeout=timeout, env=env
            )
            return proc.returncode, proc.stdout + proc.stderr
        except subprocess.TimeoutExpired as exc:
            return 124, f"timeout after {timeout}s\n{exc.stdout or ''}"

    def run_tests(self, test_paths: list[str] | None = None, timeout: int = 900) -> RunResult:
        """Run pytest and parse its JUnit report."""
        self.test_runs += 1
        with tempfile.TemporaryDirectory() as tmp:
            xml = Path(tmp) / "junit.xml"
            cmd = [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={xml}",
                *(test_paths or []),
            ]
            start = time.time()
            code, out = self.run(cmd, timeout=timeout)
            if not xml.exists():
                return RunResult(
                    ok=False,
                    errors=1,
                    failed_ids=[f"<pytest exit {code}>"],
                    duration_s=time.time() - start,
                )
            result = parse_junit(xml, time.time() - start)
            if code not in (0, 1, 5) and result.ok:
                result.ok, result.errors = False, result.errors + 1
            self.last_test_output = out
            return result

    def coverage_json(self, test_paths: list[str] | None = None) -> str | None:
        """Run the tests under coverage with per-test contexts; return the JSON path."""
        out_dir = Path(tempfile.mkdtemp(prefix="cs_cov_"))
        rc = out_dir / ".coveragerc"
        rc.write_text(f"[run]\ndynamic_context = test_function\ndata_file = {out_dir}/.coverage\n")
        code, _ = self.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                f"--rcfile={rc}",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                *(test_paths or []),
            ]
        )
        self.test_runs += 1
        json_path = out_dir / "coverage.json"
        code, _ = self.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "json",
                f"--rcfile={rc}",
                "--show-contexts",
                "-o",
                str(json_path),
            ]
        )
        return str(json_path) if code == 0 and json_path.exists() else None

    def apply_patch(self, patch: str) -> bool:
        """Apply a unified diff with git apply; return False if it does not apply."""
        if not patch.strip():
            return False
        if not patch.endswith("\n"):
            patch += "\n"
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
            f.write(patch)
        for extra in ([], ["--3way"]):
            proc = subprocess.run(
                ["git", *GIT_ID, "apply", "--check", *extra, f.name],
                cwd=self.path,
                capture_output=True,
            )
            if proc.returncode == 0:
                proc = subprocess.run(
                    ["git", *GIT_ID, "apply", *extra, f.name], cwd=self.path, capture_output=True
                )
                Path(f.name).unlink(missing_ok=True)
                return proc.returncode == 0
        Path(f.name).unlink(missing_ok=True)
        return False

    def checkpoint(self, label: str) -> str:
        """Commit everything and return the commit sha."""
        self._git("add", "-A")
        self._git("commit", "-q", "--allow-empty", "--no-verify", "-m", label)
        return self._git("rev-parse", "HEAD").strip()

    def rollback(self, to: str) -> None:
        """Reset the tree to a checkpoint, removing untracked files."""
        self._git("reset", "-q", "--hard", to)
        self._git("clean", "-q", "-fd")

    def diff(self, since: str) -> str:
        """Diff of the working tree (including new files) against a checkpoint."""
        self._git("add", "-A")
        out = self._git("diff", "--binary", "--cached", since)
        self._git("reset", "-q")
        return out

    def diff_stats(self, since: str) -> dict:
        """Lines added/removed and files deleted since a checkpoint."""
        self._git("add", "-A")
        numstat = self._git("diff", "--cached", "--numstat", since)
        deleted = self._git("diff", "--cached", "--name-only", "--diff-filter=D", since)
        self._git("reset", "-q")
        added = removed = 0
        for line in numstat.splitlines():
            a, r, _ = line.split("\t", 2)
            if a != "-":
                added, removed = added + int(a), removed + int(r)
        return {
            "lines_added": added,
            "lines_deleted": removed,
            "lines_removed": max(removed - added, 0),
            "files_removed": len(deleted.split()),
        }

    def fork(self) -> Workspace:
        """Copy this workspace into an independent one at the same state."""
        new_path = Path(tempfile.mkdtemp(prefix="cs_fork_", dir=Path(self.path).parent))
        shutil.copytree(self.path, new_path, dirs_exist_ok=True)
        clone = type(self).__new__(type(self))
        clone.__dict__.update(self.__dict__)
        clone.path = str(new_path)
        clone.test_runs = 0
        return clone

    def close(self) -> None:
        """Delete the workspace folder."""
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
