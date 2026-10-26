import json
import os
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
