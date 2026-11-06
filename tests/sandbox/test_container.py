import shutil
import subprocess

import pytest

from cleansweep.sandbox import container
from cleansweep.sandbox.workspace import GIT_ID

needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")


def _repo(root, author: str):
    root.mkdir(parents=True)
    (root / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    who = ["-c", "user.name=agent_a", "-c", f"user.email={author}"]
    subprocess.run(["git", *GIT_ID[4:], *who, "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", *GIT_ID[4:], *who, "commit", "-qm", "start"], cwd=root, check=True)
    return root


def _my_email(tmp_path, monkeypatch, email: str | None) -> None:
    config = tmp_path / "gitconfig"
    config.write_text(f"[user]\n\temail = {email}\n" if email else "")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))


def test_auto_runs_on_this_machine_only_in_a_repository_you_own(tmp_path, monkeypatch):
    _my_email(tmp_path, monkeypatch, "agent_a@example.com")
    mine = _repo(tmp_path / "mine", "agent_a@example.com")
    assert container.choose(mine) == (
        "none",
        "a git repository with commits by you (agent_a@example.com)",
    )
    (mine / "sub").mkdir()
    assert container.choose(mine / "sub")[0] == "none"  # a folder inside it
    assert container.choose(mine, untrusted=True) == ("docker", "--untrusted")
    theirs = _repo(tmp_path / "theirs", "agent_b@example.com")
    # the repository's own config cannot make it yours
    subprocess.run(["git", "config", "user.email", "agent_b@example.com"], cwd=theirs, check=True)
    mode, why = container.choose(theirs)
    assert mode == "docker" and why.endswith("no commit by you (agent_a@example.com)")
    plain = tmp_path / "plain"
    plain.mkdir()
    assert container.choose(plain) == ("docker", "not a git repository")
    assert container.choose(plain, "none") == ("none", "--sandbox none")
    _my_email(tmp_path, monkeypatch, None)
    assert container.choose(mine)[0] == "docker"
    with pytest.raises(ValueError, match="sandbox must be one of"):
        container.choose(plain, "vm")


def test_docker_missing_or_not_running_is_a_sandbox_error(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(container.subprocess, "run", missing)
    with pytest.raises(container.SandboxError, match="Docker is not installed"):
        container.check_docker()
    down = subprocess.CompletedProcess(["docker", "info"], 1, "", "Cannot connect")
    monkeypatch.setattr(container.subprocess, "run", lambda *a, **k: down)
    with pytest.raises(container.SandboxError, match="Docker is not running"):
        container.check_docker()


@pytest.mark.docker
@needs_docker
def test_project_code_has_no_network_after_the_install(tmp_path):
    root = _repo(tmp_path / "ws", "agent_a@example.com")
    ws = container.open_container(root, "local:ws", {}, install=[])
    try:
        assert ws.install_info.startswith("installed in the container")  # pytest came over it
        probe = "import pytest, socket; socket.create_connection(('1.1.1.1', 53), timeout=5)"
        code, out = ws.run(["python", "-c", probe])
        assert code != 0 and ("OSError" in out or "unreachable" in out), out
    finally:
        ws.close()
    assert root.is_dir()  # the container goes, the workspace stays
