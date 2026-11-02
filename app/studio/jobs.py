"""Start clean, sweep and watch runs as child processes; each writes its events to its folder."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from cleansweep.agents.budgets import parse_budget
from cleansweep.core.models import METHODS

from .files import ROOT

KINDS = ("clean", "sweep", "watch")
MODES = ("safe", "thorough")
JUDGE_MODES = ("gatekeeper", "advisory", "off")
TARGETS = {
    "toy": ROOT / "tests" / "fixtures" / "toy_repo",
    "demo": ROOT / "demo" / "shop_app",
    "demo-prepared": ROOT / ".cleansweep" / "demo" / "shop_app",
}
MODEL = re.compile(r"^[\w.:/-]{1,80}$")


class JobError(ValueError):
    """A run request that cannot start."""


def watch_available() -> bool:
    """True once the `cleansweep watch` module exists."""
    try:
        return importlib.util.find_spec("cleansweep.agents.watch") is not None
    except ModuleNotFoundError:
        return False


def targets() -> list[dict]:
    """The launcher's shortcuts that exist on this machine."""
    labels = {
        "toy": "Toy repo",
        "demo": "Demo app",
        "demo-prepared": "Prepared demo app + feature (demo/prepare_demo.sh)",
    }
    return [{"key": k, "label": labels[k]} for k, p in TARGETS.items() if p.is_dir()]


@dataclass
class Job:
    id: str
    kind: str
    target: str
    folder: Path
    log: Path
    proc: subprocess.Popen
    started: float = field(default_factory=time.time)
    stopped: bool = False

    def status(self) -> str:
        code = self.proc.poll()
        if code is None:
            return "running"
        if self.stopped:
            return "stopped"
        return "done" if code == 0 else "failed"

    def info(self, runs: Path) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "root": "runs",
            "path": self.folder.relative_to(runs).as_posix(),
            "status": self.status(),
            "exit_code": self.proc.poll(),
            "started": self.started,
        }


def _target(value: str) -> Path:
    if value in TARGETS:
        return TARGETS[value]
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise JobError(f"not a folder (give an absolute path): {value}")
    return path.resolve()


def command(spec: dict, run_id: str, runs: Path) -> tuple[list[str], Path, dict]:
    """The child process for a run request: argv, its run folder, extra environment."""
    kind = spec.get("kind", "clean")
    if kind not in KINDS:
        raise JobError(f"kind must be one of {KINDS}")
    target = _target(str(spec.get("target") or "toy"))
    model = spec.get("model") or None
    if model and not MODEL.match(model):
        raise JobError(f"not a model name: {model}")
    env = {"VOYAGER_MODEL": model} if model else {}
    py = [sys.executable, "-m"]
    folder = runs / run_id
    if kind == "sweep":
        method = spec.get("method") or "cleansweep"
        judge = spec.get("judge_mode") or "gatekeeper"
        if method not in METHODS or judge not in JUDGE_MODES:
            raise JobError(f"method must be one of {METHODS}, judge mode one of {JUDGE_MODES}")
        argv = [*py, "app.studio.worker", "--target", str(target), "--method", method]
        argv += ["--judge-mode", judge, "--run-id", run_id, "--out", str(runs)]
        return argv, folder, env
    mode = spec.get("mode") or "safe"
    if mode not in MODES:
        raise JobError(f"mode must be one of {MODES}")
    flags = ["--no-llm"] if spec.get("no_llm") else []
    if kind == "clean":
        argv = [*py, "cleansweep", "clean", str(target), "--out", str(folder), "--mode", mode]
        if spec.get("budget"):
            parse_budget(spec["budget"])
            argv += ["--budget", spec["budget"]]
        if model:
            argv += ["--model", model]
        if spec.get("dry_run"):
            flags.append("--dry-run")
        return argv + flags, folder, {}
    if not watch_available():
        raise JobError("watch mode is not available yet")
    if not (target / ".git").exists():
        raise JobError(f"watch needs a git repository: {target}")
    polls, interval = int(spec.get("polls") or 1), float(spec.get("interval") or 60)
    budget_tests = int(spec.get("budget_tests") or 0)
    if not (1 <= polls <= 1000 and interval >= 1 and budget_tests >= 0):
        raise JobError("polls must be 1-1000, interval at least 1 s, test budget 0 or more")
    argv = [*py, "cleansweep", "watch", str(target), "--out", str(folder), "--mode", mode]
    argv += ["--polls", str(polls), "--interval", str(interval)]
    argv += ["--budget-tests", str(budget_tests)]
    return argv + flags, folder, env


class JobManager:
    """Runs started from Studio in this server process."""

    def __init__(self, runs: Path):
        self.runs = Path(runs)
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, spec: dict) -> Job:
        """Validate a run request and start its process."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = re.sub(r"[^\w-]", "_", Path(str(spec.get("target") or "toy")).name)[:40]
        run_id = f"{stamp}_{name}_{spec.get('kind', 'clean')}"
        with self._lock:
            if run_id in self.jobs:
                raise JobError("a run with this name just started; try again in a second")
        try:
            argv, folder, extra = command(spec, run_id, self.runs)
        except ValueError as exc:
            raise JobError(str(exc)) from None
        logs = self.runs / "_jobs"
        logs.mkdir(parents=True, exist_ok=True)
        # an empty run folder at once, so the page can follow it before the first event
        folder.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, **extra}
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(ROOT / "src"), str(ROOT), env.get("PYTHONPATH", "")) if p
        )
        log = logs / f"{run_id}.log"
        with log.open("w", encoding="utf-8") as out:
            proc = subprocess.Popen(
                argv, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT, text=True
            )
        job = Job(run_id, spec.get("kind", "clean"), str(spec.get("target")), folder, log, proc)
        with self._lock:
            self.jobs[run_id] = job
        return job

    def list(self) -> list[dict]:
        with self._lock:
            jobs = list(self.jobs.values())
        return [j.info(self.runs) for j in sorted(jobs, key=lambda j: j.started, reverse=True)]

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self.jobs.get(job_id)

    def job_for(self, folder: Path) -> Job | None:
        """The job of this server that writes to that folder, if any."""
        with self._lock:
            jobs = list(self.jobs.values())
        real = os.path.realpath(folder)
        return next((j for j in jobs if os.path.realpath(j.folder) == real), None)

    def running(self, folder: Path) -> bool:
        """True while a job of this server writes to that folder."""
        job = self.job_for(folder)
        return job is not None and job.status() == "running"

    def stop(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is not None and job.status() == "running":
            job.stopped = True
            job.proc.terminate()
            try:
                job.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                job.proc.kill()
        return job
