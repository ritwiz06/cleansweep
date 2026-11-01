import sys

import pytest

from cleansweep.agents import clean_project, environment, tester
from cleansweep.agents.delivery import prepare_workspace
from cleansweep.agents.runtime import Runtime

from .conftest import write_project

SRC_LAYOUT = {
    "pyproject.toml": (
        '[project]\nname = "srcpkg"\nversion = "0.1"\n\n'
        "[tool.pytest.ini_options]\npythonpath = []\n"
    ),
    "src/srcpkg/__init__.py": (
        "def answer():\n    return 42\n\n\ndef legacy_unused():\n    return 0\n"
    ),
    "tests/test_srcpkg.py": (
        "from srcpkg import answer\n\n\ndef test_answer():\n    assert answer() == 42\n"
    ),
}


def test_pip_commands():
    assert environment.pip_commands("pip install -e .[test]") == [["-e", ".[test]"]]
    two = environment.pip_commands("pip install -r a.txt && pip install -r b.txt")
    assert two == [["-r", "a.txt"], ["-r", "b.txt"]]
    assert environment.pip_commands("none needed (no packaging or requirements files)") == []


def test_a_src_layout_imports_the_copy_and_install_can_be_off(tmp_path, agent_cfg):
    root = write_project(tmp_path / "srcproj", SRC_LAYOUT)
    agent_cfg["core"]["agents"]["install"] = "off"
    ws, _ = prepare_workspace(root, tmp_path / "ws", agent_cfg["core"]["sandbox"])
    rt = Runtime(ws, agent_cfg, None, tmp_path / "out")
    rt.brief = {"install_command": "pip install -e ."}
    info = environment.prepare(rt)
    assert info == {"python": sys.executable, "install": "not needed", "pythonpath": "src"}
    assert ws.extra_env["PYTHONPATH"].startswith(str(tmp_path / "ws" / "src"))
    tester.baseline(rt)  # the copy's src is importable without installing it
    assert rt.baseline["passed"] == 1


@pytest.mark.network
def test_the_project_is_installed_into_its_own_venv(tmp_path, agent_cfg):
    root = write_project(tmp_path / "srcproj", SRC_LAYOUT)
    agent_cfg["core"]["agents"]["install"] = "auto"
    result = clean_project(str(root), agent_cfg, out=str(tmp_path / "o"), use_llm=False)
    report = (tmp_path / "o" / "CLEANUP_REPORT.md").read_text()
    assert "installed into .cs_venv" in report, report[:1500]
    assert not (tmp_path / "o" / "workspace" / ".cs_venv").exists()
    assert result["report"].stats["agentic"]["baseline"]["passed"] == 1  # run with the venv
    assert result["summary"]["verdict"] == "everything runs"
    assert result["summary"]["applied"] == 1  # legacy_unused, checked by the venv's tests


def test_slow_suites_run_related_tests_per_package_and_the_full_suite_at_the_end(
    mini, agent_cfg, tmp_path
):
    agent_cfg["core"]["agents"]["full_suite_max_s"] = 0
    result = clean_project(str(mini), agent_cfg, out=str(tmp_path / "o"), use_llm=False)
    assert result["summary"]["verdict"] == "everything runs"
    # 2 baseline runs + related tests per package + 1 final: fewer than a full suite per package
    assert result["report"].stats["test_runs"] < 2 + 3 + 1 + 3


def test_test_args_and_exclusions_reach_the_run(mini, agent_cfg, tmp_path):
    result = clean_project(
        str(mini),
        agent_cfg,
        out=str(tmp_path / "o"),
        use_llm=False,
        test_args=["-k", "test_total"],
        exclude=["shop/"],
    )
    agentic = result["report"].stats["agentic"]
    assert agentic["baseline"]["passed"] == 1  # only test_total ran
    assert all(not i.unit.path.startswith("shop/") for i in result["report"].plan.items)
