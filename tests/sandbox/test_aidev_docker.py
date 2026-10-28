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
