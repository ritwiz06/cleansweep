import json
import os
import subprocess
from pathlib import Path

import pytest

from cleansweep.core.config import load_config

# Git hooks (pre-push) export these, absolute in worktrees. Tests run git in temporary
# folders, and with them set those commands would write to this repository instead.
for _var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX"):
    os.environ.pop(_var, None)

FIXTURES = Path(__file__).parent / "fixtures"
TOY = FIXTURES / "toy_repo"


@pytest.fixture
def toy_repo() -> str:
    return str(TOY)


@pytest.fixture
def toy_expected() -> list[dict]:
    return json.loads((FIXTURES / "toy_repo_expected.json").read_text())["items"]


@pytest.fixture
def sandbox_cfg(tmp_path) -> dict:
    return {"work_dir": str(tmp_path / "ws"), "quarantine_dir": str(tmp_path / "quarantine")}


@pytest.fixture
def cfg(sandbox_cfg) -> dict:
    """Full config with LLM off and workspaces under tmp_path."""
    return load_config({"core": {"sandbox": sandbox_cfg, "llm": {"enabled": False}}})


@pytest.fixture
def toy_ws(toy_repo, sandbox_cfg):
    from cleansweep.sandbox import open_workspace

    ws = open_workspace(toy_repo, sandbox_cfg)
    yield ws
    ws.close()


_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
HELPER = """def normalize(value):
    text = str(value).strip()
    text = text.lower()
    parts = text.split()
    return "-".join(parts)
"""
OLD = """

def old_unused(a, b):
    total = a + b
    total = total * 2
    total = total - 1
    return total
"""
AGENT = """import os


def helper_copy(value):
    text = str(value).strip()
    text = text.lower()
    parts = text.split()
    return "-".join(parts)


def new_dead(x):
    y = x + 1
    y = y * 3
    y = y - 2
    return y
"""


def _commit(repo, message):
    subprocess.run([*_GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*_GIT, "commit", "-q", "-m", message], cwd=repo, check=True)


@pytest.fixture
def agent_repo(tmp_path):
    """A two-commit repo (base, agent patch): old dead code in base, slop in the agent patch."""
    repo = tmp_path / "proj"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("")
    (repo / "pkg" / "core.py").write_text(HELPER + OLD)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_core.py").write_text(
        "from pkg.core import normalize\n\n\ndef test_normalize():\n"
        "    assert normalize(' A b ') == 'a-b'\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _commit(repo, "base")
    (repo / "pkg" / "core.py").write_text(AGENT + "\n\n" + HELPER + OLD)
    (repo / "reproduce_issue.py").write_text(
        "from pkg.core import normalize\nprint(normalize('X'))\n"
    )
    (repo / "test_scratch.py").write_text("def test_quick():\n    assert 1 + 1 == 2\n")
    (repo / "sample_app").mkdir()
    (repo / "sample_app" / "app.py").write_text("print('sample')\n")
    _commit(repo, "agent patch")
    return str(repo)
