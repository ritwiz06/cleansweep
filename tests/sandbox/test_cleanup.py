import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from cleansweep.sandbox.cleanup import sweep_orphans
from cleansweep.sandbox.workspace import OWNER_FILE
from cleansweep.workflow import run_sweep

SRC = Path(__file__).resolve().parents[2] / "src"
CHILD = """
import signal, sys, time
for sig in (signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, signal.SIG_DFL)
signal.signal(signal.SIGINT, signal.default_int_handler)
from cleansweep.sandbox import open_workspace
from cleansweep.sandbox.cleanup import exit_on_signals
exit_on_signals()
with open_workspace(sys.argv[1], {"work_dir": sys.argv[2]}):
    print("open", flush=True)
    time.sleep(60)
"""


def _left(cfg) -> list[str]:
    return os.listdir(cfg["core"]["sandbox"]["work_dir"])


def test_a_run_that_succeeds_leaves_no_workspace(toy_repo, cfg):
    run_sweep(toy_repo, cfg, method="cleansweep")
    assert _left(cfg) == []
    assert not [p for p in os.listdir(tempfile.gettempdir()) if p.startswith("cs_")]


def test_a_run_that_raises_leaves_no_workspace(toy_repo, cfg, monkeypatch):
    import cleansweep.workflow.sweep as sweep

    def broken(*args, **kwargs):
        raise RuntimeError("broken")

    monkeypatch.setattr(sweep, "build_graph", broken)
    with pytest.raises(RuntimeError):
        run_sweep(toy_repo, cfg, method="cleansweep")
    assert _left(cfg) == []


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP, signal.SIGINT])
def test_an_interrupted_run_leaves_no_workspace(toy_repo, tmp_path, sig):
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    work = tmp_path / "ws"
    proc = subprocess.Popen(
        [sys.executable, "-c", CHILD, toy_repo, str(work)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    assert proc.stdout.readline().strip() == "open"
    proc.send_signal(sig)
    proc.wait(timeout=30)
    assert os.listdir(work) == []


def test_a_kept_workspace_stays(toy_repo, cfg, monkeypatch):
    import cleansweep.workflow.sweep as sweep

    cfg["core"]["sandbox"]["keep_workspace"] = True
    monkeypatch.setattr(sweep, "build_graph", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        run_sweep(toy_repo, cfg, method="cleansweep")
    assert len(_left(cfg)) == 1


def test_the_startup_sweep_removes_only_old_orphans(tmp_path):
    work, old = tmp_path / "ws", time.time() - 2 * 86400
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()

    def folder(root: Path, name: str, owner: int | None = None, repo: bool = True) -> Path:
        path = root / name
        (path / ".git" if repo else path).mkdir(parents=True)
        if owner:
            (path / ".git" / OWNER_FILE).write_text(str(owner))
        os.utime(path, (old, old))
        return path

    folder(work, "proj-1")
    folder(work, "proj-2", owner=gone.pid)
    kept = [folder(work, "proj-3", owner=os.getpid()), folder(work, "run", repo=False)]
    young = work / "proj-4"
    (young / ".git").mkdir(parents=True)
    temp = Path(tempfile.gettempdir())
    folder(temp, "cs_probe_x", repo=False)
    kept.append(folder(temp, "someone_elses", repo=False))
    removed = sweep_orphans({"work_dir": str(work)})
    assert sorted(Path(p).name for p in removed) == ["cs_probe_x", "proj-1", "proj-2"]
    assert all(p.exists() for p in [*kept, young])
