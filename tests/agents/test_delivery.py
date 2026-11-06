import subprocess

from cleansweep.agents.delivery import prepare_workspace
from cleansweep.sandbox.workspace import GIT_ID


def test_an_untrusted_repository_is_copied_without_running_its_git_config(tmp_path):
    src = tmp_path / "theirs"
    src.mkdir()
    (src / ".gitignore").write_text("*.log\n")
    (src / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    subprocess.run(["git", *GIT_ID, "add", "-A"], cwd=src, check=True)
    subprocess.run(["git", *GIT_ID, "commit", "-qm", "start"], cwd=src, check=True)
    marker = tmp_path / "ran"
    hook = tmp_path / "hook.sh"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    hook.chmod(0o755)
    subprocess.run(["git", "config", "core.fsmonitor", str(hook)], cwd=src, check=True)
    (src / "a.py").write_text("x = 2\n")
    (src / "new.py").write_text("y = 1\n")
    (src / "run.log").write_text("ignored\n")
    ws, info = prepare_workspace(src, tmp_path / "ws", {}, trusted=False)
    assert not marker.exists()  # its fsmonitor command never ran
    assert info["uncommitted_changes"] and (tmp_path / "ws" / "a.py").read_text() == "x = 2\n"
    assert (tmp_path / "ws" / "new.py").exists() and not (tmp_path / "ws" / "run.log").exists()
    assert ws._git("status", "--porcelain") == ""
