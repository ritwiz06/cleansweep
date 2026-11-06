import shutil
import subprocess

import pytest

needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


@pytest.mark.docker
@needs_docker
def test_aidev_workspace_installs_tests_offline_and_rolls_back(tmp_path, sandbox_cfg):
    from cleansweep.sandbox import open_workspace

    clone = tmp_path / "clones" / "o__tiny"
    (clone / "tiny").mkdir(parents=True)
    (clone / "tiny" / "__init__.py").write_text("def double(x):\n    return 2 * x\n")
    (clone / "pyproject.toml").write_text(
        '[project]\nname = "tiny"\nversion = "0.1"\n[build-system]\n'
        'requires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n'
    )
    (clone / "test_tiny.py").write_text(
        "import socket\n"
        "from tiny import double\n\n\n"
        "def test_double():\n"
        "    assert double(2) == 4\n\n\n"
        "def test_no_network():\n"
        "    try:\n"
        "        socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    except OSError:\n"
        "        return\n"
        "    raise AssertionError('network reachable')\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=clone, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=clone, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "c"], cwd=clone, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True
    ).stdout.strip()
    ws = open_workspace(
        f"aidev:o/tiny@{sha}", {**sandbox_cfg, "aidev_clones": str(tmp_path / "clones")}
    )
    try:
        result = ws.run_tests(None)
        assert result.ok and result.passed == 2  # tests ran, with no network
        start = ws.checkpoint("x")
        with open(f"{ws.path}/tiny/__init__.py", "a") as f:
            f.write("\nBROKEN = 1 / 0\n")
        assert not ws.run_tests(None).ok
        ws.rollback(start)
        assert ws.run_tests(None).ok
    finally:
        ws.close()


@pytest.mark.docker
@needs_docker
def test_aidev_workspace_stores_the_agent_scope(sandbox_cfg):
    import json
    from pathlib import Path

    from cleansweep.analysis import build_graph
    from cleansweep.analysis.scope import agent_scope
    from cleansweep.sandbox import open_workspace
    from cleansweep.sandbox.aidev_docker import clone_dir

    split = Path(__file__).resolve().parents[2] / "data" / "splits" / "aidev_repos.json"
    repo = min(json.loads(split.read_text()), key=lambda e: int(e["test_seconds"]))
    if not (clone_dir({}, repo["full_name"]) / ".git").exists():
        pytest.skip("AIDev clones not downloaded")
    ws = open_workspace(f"aidev:{repo['full_name']}@{repo['head_sha']}", sandbox_cfg)
    try:
        scope = agent_scope(ws.path, build_graph(ws.path))
        assert scope is not None and scope.files and scope.units
        assert not scope.outside_project(sorted(scope.files_added or scope.files)[0])
    finally:
        ws.close()


@pytest.mark.docker
@needs_docker
def test_aidev_workspace_hides_and_restores_packages(tmp_path, sandbox_cfg):
    from cleansweep.sandbox import open_workspace

    clone = tmp_path / "clones" / "o__dep"
    (clone / "dep").mkdir(parents=True)
    (clone / "dep" / "__init__.py").write_text("")
    (clone / "pyproject.toml").write_text(
        '[project]\nname = "dep"\nversion = "0.1"\ndependencies = ["six"]\n[build-system]\n'
        'requires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n'
    )
    (clone / "test_dep.py").write_text("def test_six():\n    import six\n\n    assert six.PY3\n")
    subprocess.run(["git", "init", "-q"], cwd=clone, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=clone, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "c"], cwd=clone, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True
    ).stdout.strip()
    ws = open_workspace(
        f"aidev:o/dep@{sha}", {**sandbox_cfg, "aidev_clones": str(tmp_path / "clones")}
    )
    try:
        assert ws.run_tests(None).ok
        states = ws.hide_packages(["six", "iniconfig", "nope"])
        assert states["six"] == "hidden"
        assert states["iniconfig"].startswith("required by") and "pytest" in states["iniconfig"]
        assert states["nope"] == "not installed"
        assert not ws.run_tests(None).ok
        ws.restore_packages()
        assert ws.run_tests(None).ok
    finally:
        ws.close()


class _FakeContainer:
    """Stands in for docker: a dict of the container's files; `stale` paths keep old content."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.stale: set[str] = set()


def _fake_workspace(tmp_path, monkeypatch):
    import hashlib
    import json

    from cleansweep.sandbox import aidev_docker

    root = tmp_path / "ws"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("A = 1\n")
    (root / "gone.py").write_text("B = 2\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=root, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "c"], cwd=root, check=True)
    box = _FakeContainer()
    ws = aidev_docker.AidevWorkspace(root, "aidev:o/x", {}, "cs-fake")

    def send(paths):
        for rel in paths:
            full = root / rel
            files = [full] if full.is_file() else [p for p in full.rglob("*") if p.is_file()]
            for f in files:
                key = str(f.relative_to(root))
                if key not in box.stale:
                    box.files[key] = f.read_bytes()

    def container_py(script, paths):
        if script == aidev_docker.REMOVE_PY:
            for p in paths:
                if p not in box.stale:
                    box.files.pop(p, None)
            return ""
        return json.dumps(
            {p: hashlib.sha256(box.files[p]).hexdigest() if p in box.files else None for p in paths}
        )

    monkeypatch.setattr(ws, "_send", send)
    monkeypatch.setattr(ws, "_container_py", container_py)
    ws.copy_in()
    return ws, box, root


def test_sync_pushes_changes_and_deletions_and_checks_their_hashes(tmp_path, monkeypatch):
    ws, box, root = _fake_workspace(tmp_path, monkeypatch)
    assert box.files["pkg/a.py"] == b"A = 1\n" and not any(k.startswith(".git/") for k in ws._files)
    (root / "pkg" / "a.py").write_text("A = 2\n")
    (root / "gone.py").unlink()
    (root / "new.py").write_text("C = 3\n")
    ws.sync()
    assert box.files["pkg/a.py"] == b"A = 2\n" and box.files["new.py"] == b"C = 3\n"
    assert "gone.py" not in box.files
    assert ws._touched == {"pkg/a.py", "gone.py", "new.py"} and ws.stale_retries == 0


def test_a_file_that_stays_stale_fails_the_command_never_passes_it(tmp_path, monkeypatch):
    from cleansweep.sandbox import aidev_docker

    ws, box, root = _fake_workspace(tmp_path, monkeypatch)
    box.stale.add("gone.py")  # the container keeps showing a deleted file
    (root / "gone.py").unlink()
    with pytest.raises(aidev_docker.StaleWorkspace, match="gone.py"):
        ws.sync()
    assert ws.stale_retries == 1
    monkeypatch.setattr(aidev_docker, "_docker", lambda *a, **k: None)  # nothing may run
    code, out = ws._exec("python -m pytest", 60)
    assert code == aidev_docker.STALE_CODE and "stale workspace" in out
    result = ws._junit_run(["python", "-m", "pytest"], 60)
    assert not result.ok and result.failed_ids == ["<stale workspace>"]


@pytest.mark.docker
@needs_docker
def test_the_container_sees_every_delete_and_replace_at_once(tmp_path, sandbox_cfg):
    """Regression: through a bind mount the container could see a deleted file, or the old
    content of a file git or an atomic write replaced; the copied workspace never does."""
    import os

    from cleansweep.sandbox import open_workspace

    clone = tmp_path / "clones" / "o__tiny"
    clone.mkdir(parents=True)
    (clone / "mod.py").write_text("A = 0\n" * 50)
    (clone / "gone.py").write_text("B = 2\n")
    subprocess.run(["git", "init", "-q"], cwd=clone, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=clone, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "c"], cwd=clone, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True, text=True
    ).stdout.strip()
    cfg = {**sandbox_cfg, "aidev_clones": str(tmp_path / "clones"), "install": False}
    ws = open_workspace(f"aidev:o/tiny@{sha}", cfg)
    try:
        for i in range(25):
            os.remove(f"{ws.path}/gone.py")
            assert ws.run(["test", "!", "-e", "gone.py"])[0] == 0
            subprocess.run([*GIT, "checkout", "-q", "--", "gone.py"], cwd=ws.path, check=True)
            body = f"A = {i}\n" * 50
            with open(f"{ws.path}/.tmp", "w") as f:
                f.write(body)
            os.replace(f"{ws.path}/.tmp", f"{ws.path}/mod.py")
            check = f"print(open('mod.py').read() == {body!r})"
            code, out = ws.run(["python", "-c", check])
            assert code == 0 and out.strip() == "True"
        assert ws.stale_retries == 0
    finally:
        ws.close()
