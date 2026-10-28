from cleansweep.analysis import build_graph
from cleansweep.analysis.minhash import find_duplicates
from cleansweep.analysis.scope import agent_commit, agent_scope


def test_scope_covers_only_what_the_agent_wrote(agent_repo):
    assert agent_commit(agent_repo)
    scope = agent_scope(agent_repo, build_graph(agent_repo))
    assert scope.files_added == {"reproduce_issue.py", "test_scratch.py", "sample_app/app.py"}
    assert scope.outside_project("sample_app/app.py") and scope.outside_project("test_scratch.py")
    assert not scope.outside_project("pkg/core.py")
    assert "pkg/core.py::helper_copy" in scope.units and "pkg/core.py::new_dead" in scope.units
    assert "pkg/core.py::old_unused" not in scope.units
    assert "pkg/core.py::normalize" not in scope.units


def test_no_agent_commit_means_no_scope(toy_ws):
    assert agent_scope(toy_ws.path, build_graph(toy_ws.path)) is None


def test_find_duplicates_k_by_n(agent_repo):
    pairs = find_duplicates(agent_repo, 0.8, only={"pkg/core.py::helper_copy"})
    assert {(a.key, b.key) for a, b, _ in pairs} == {
        ("pkg/core.py::helper_copy", "pkg/core.py::normalize")
    }


def _git(repo, *args):
    import subprocess

    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    return subprocess.run([*git, *args], cwd=repo, capture_output=True, text=True).stdout.strip()


def history_repo(tmp_path):
    """human commit, agent commit (changes core.py, adds new.py and a root script), human commit."""
    repo = tmp_path / "clone"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("")
    (repo / "pkg" / "core.py").write_text("def keep(x):\n    return x\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "human")
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "pkg" / "core.py").write_text(
        "def keep(x):\n    return x\n\n\ndef agent_fn(y):\n    return y * 2\n"
    )
    (repo / "pkg" / "new.py").write_text("def made(z):\n    return z\n")
    (repo / "demo.py").write_text("print('demo')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "agent pull request")
    agent = _git(repo, "rev-parse", "HEAD")
    (repo / "pkg" / "core.py").write_text(
        "def keep(x):\n    return x + 0\n\n\ndef agent_fn(y):\n    return y * 2\n"
    )
    _git(repo, "commit", "-q", "-am", "human again")
    return repo, first, agent


def test_blame_scope_finds_agent_lines_and_files(tmp_path):
    from cleansweep.analysis.scope import blame_scope

    repo, first, agent = history_repo(tmp_path)
    scope = blame_scope(str(repo), _git(repo, "rev-parse", "HEAD"), {agent}, first)
    assert scope["files_added"] == ["demo.py", "pkg/new.py"]
    assert scope["lines"] == {"pkg/core.py": [3, 4, 5, 6]}


def test_stored_scope_gives_units_without_scratch_files(tmp_path, monkeypatch):
    import shutil

    import cleansweep.data.aidev as aidev
    from cleansweep.sandbox.aidev_docker import write_scope

    repo, first, agent = history_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    ws = tmp_path / "ws"
    shutil.copytree(repo, ws, ignore=shutil.ignore_patterns(".git"))
    _git(ws, "init", "-q")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "base")
    monkeypatch.setattr(aidev, "agent_history", lambda name, sha=None: ({agent}, first))
    assert write_scope(ws, str(repo), "owner/name", head)
    scope = agent_scope(str(ws), build_graph(str(ws)))
    assert "pkg/core.py::agent_fn" in scope.units and "pkg/new.py::made" in scope.units
    assert "pkg/core.py::keep" not in scope.units
    assert not scope.outside_project("demo.py")  # merged pull requests leave no scratch files
