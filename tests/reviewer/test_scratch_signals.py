import subprocess

from cleansweep.analysis import build_graph
from cleansweep.analysis.graph import module_in_configs
from cleansweep.analysis.scope import agent_scope
from cleansweep.reviewer import run_detectors
from cleansweep.reviewer.judge import scratch_context, signals

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


def two_commits(repo, base: dict, agent: dict) -> str:
    """A repo with a base commit and an "agent patch" commit adding `agent` files."""
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for files, message in ((base, "base"), (agent, "agent patch")):
        for path, text in files.items():
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(text)
        subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
        subprocess.run([*GIT, "commit", "-q", "-m", message], cwd=repo, check=True)
    return str(repo)


BASE = {
    "pkg/__init__.py": "",
    "pkg/core.py": "def f():\n    return 'admin'\n",
    "setup.cfg": "[tool]\napps = admin models tests\n",
}
AGENT = {
    "sample_app/__init__.py": "",
    "sample_app/admin.py": "def register():\n    return 1\n",
    "sample_app/tests.py": (
        "from sample_app.admin import register\n\n\ndef test_r():\n    assert register()\n"
    ),
    "sample_app/settings.py": "INSTALLED_APPS = ['sample_app.admin']\n",
}


def leftover_signals(repo):
    graph = build_graph(repo)
    items = run_detectors(repo, graph, agent_scope(repo, graph))
    ctx = scratch_context(items, repo, graph)
    return {
        i.unit.path: signals(i, graph, repo, ctx) for i in items if i.category == "leftover_file"
    }


def test_scratch_files_only_count_project_code(tmp_path):
    repo = two_commits(tmp_path / "r", BASE, AGENT)
    sig = leftover_signals(repo)["sample_app/admin.py"]
    assert sig["created_by_agent_patch"]
    assert sig["imported_by"] == 0  # only another scratch file imports it
    assert sig["mentioned_in_config"] is False  # setup.cfg says "admin", not sample_app.admin
    assert sig["dynamic_risk"] is False  # the string naming it is in a scratch file


def test_project_code_still_counts(tmp_path):
    base = {**BASE, "setup.cfg": "[tool]\nplugins = sample_app.admin\n"}
    agent = {
        **AGENT,
        "pkg/core.py": (
            "from sample_app.admin import register\n\n\ndef f():\n    return register()\n"
        ),
    }
    repo = two_commits(tmp_path / "r", base, agent)
    assert module_in_configs(repo, "sample_app/admin.py")
    graph = build_graph(repo)
    items = run_detectors(repo, graph, agent_scope(repo, graph))
    # imported by project code the agent changed, so it is not a leftover at all
    assert "sample_app/admin.py" not in {i.unit.path for i in items}


def test_bare_name_in_config_is_not_a_mention(tmp_path):
    repo = two_commits(tmp_path / "r", BASE, AGENT)
    assert not module_in_configs(repo, "sample_app/admin.py")
    assert module_in_configs(repo, "admin.py")  # a root file is imported by its bare name
