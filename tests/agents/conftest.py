import hashlib
from pathlib import Path

import pytest

from cleansweep.core.config import load_config

MINI = {
    "pytest.ini": "[pytest]\npythonpath = .\n",
    "shop/__init__.py": "",
    "shop/core.py": (
        "import os\n\n\n"
        "def total(prices):\n    return sum(prices)\n\n\n"
        "def legacy_alpha(x):\n    return x * 2\n"
    ),
    "shop/extra.py": ("def used():\n    return 1\n\n\ndef legacy_beta(y):\n    return y + 1\n"),
    "tests/__init__.py": "",
    "tests/test_shop.py": (
        "from shop.core import total\nfrom shop.extra import used\n\n\n"
        "def test_total():\n    assert total([1, 2]) == 3\n\n\n"
        "def test_used():\n    assert used() == 1\n"
    ),
}


def write_project(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


@pytest.fixture(autouse=True)
def _on_this_machine(monkeypatch):
    """`clean` from the command line runs the projects here unless a test asks for Docker."""
    monkeypatch.setenv("CLEANSWEEP_SANDBOX", "none")


@pytest.fixture
def mini(tmp_path) -> Path:
    """A small project: an unused import and two dead functions named legacy_*."""
    return write_project(tmp_path / "mini", MINI)


@pytest.fixture
def agent_cfg(tmp_path) -> dict:
    """Config with the LLM off, no installs, and every cache and workspace under tmp_path."""
    return load_config(
        {
            "core": {
                "sandbox": {
                    "work_dir": str(tmp_path / "ws"),
                    "quarantine_dir": str(tmp_path / "q"),
                },
                "llm": {"enabled": False, "cache_path": str(tmp_path / "llm.sqlite")},
                "guard": {"probe_cache_dir": str(tmp_path / "probes")},
                "agents": {"baseline_runs": 2, "install": "off"},  # no pip in offline tests
            }
        }
    )
