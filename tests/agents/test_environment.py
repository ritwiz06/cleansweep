import os
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


PEP621 = (
    '[project]\nname = "p"\nversion = "1"\n'
    '[project.optional-dependencies]\ntest = ["pytest"]\ndocs = ["sphinx"]\n'
    '[dependency-groups]\nlint = ["ruff"]\ndev = ["hypothesis", {include-group = "lint"}]\n'
)
POETRY = (
    '[tool.poetry]\nname = "p"\nversion = "1"\n'
    '[tool.poetry.dependencies]\npython = "^3.11"\n'
    '[tool.poetry.group.test.dependencies]\npytest = "^8"\n'
    '[build-system]\nrequires = ["poetry-core"]\nbuild-backend = "poetry.core.masonry.api"\n'
)


def _plan(tmp_path, files, tools=()):
    root = write_project(tmp_path, files)
    return environment.install_plan(root, which=lambda name: name if name in tools else None)


def test_a_pep_621_project_with_extras_and_dependency_groups(tmp_path):
    plan = _plan(tmp_path, {"pyproject.toml": PEP621, "requirements-docs.txt": "sphinx\n"})
    assert plan["tool"] == "pip" and plan["steps"] == [
        ["pip", "install", "-e", ".[test]"],
        ["pip", "install", "hypothesis", "ruff"],
    ]
    assert plan["fallback"][0] == ["pip", "install", "-e", "."]
    assert environment.describe(plan).startswith("pip install -e '.[test]' && pip install")


def test_poetry_and_uv_with_their_lock_files_else_pip(tmp_path):
    files = {"pyproject.toml": POETRY, "poetry.lock": ""}
    plan = _plan(tmp_path / "a", files, tools=("poetry",))
    assert plan["steps"] == [["poetry", "install", "--no-interaction", "--with", "test"]]
    assert plan["fallback"] == [["pip", "install", "-e", "."], ["pip", "install", "pytest"]]
    assert _plan(tmp_path / "b", files)["steps"] == plan["fallback"]  # poetry not installed
    files = {"pyproject.toml": PEP621, "uv.lock": ""}
    plan = _plan(tmp_path / "c", files, tools=("uv",))
    assert plan["steps"] == [["uv", "sync", "--frozen", "--group", "dev", "--extra", "test"]]
    assert plan["tool"] == "uv" and plan["fallback"][0] == ["pip", "install", "-e", ".[test]"]


def test_requirements_files_and_setup_py_extras(tmp_path):
    files = {"requirements.txt": "a\n", "requirements-dev.txt": "b\n", "requirements-docs.txt": ""}
    assert _plan(tmp_path / "a", files)["steps"] == [
        ["pip", "install", "-r", "requirements-dev.txt"],
        ["pip", "install", "-r", "requirements.txt"],
    ]
    only_prod = _plan(tmp_path / "b", {"requirements-prod.txt": "a\n"})
    assert only_prod["steps"] == [["pip", "install", "-r", "requirements-prod.txt"]]
    setup = "from setuptools import setup\nX = {'test': ['pytest']}\nsetup(extras_require=X)\n"
    assert _plan(tmp_path / "c", {"setup.py": setup})["steps"] == [
        ["pip", "install", "-e", ".[test]"]
    ]
    assert environment.describe(_plan(tmp_path / "d", {"a.py": ""})) == environment.NOTHING


def test_a_tool_install_runs_in_the_venv_and_falls_back(tmp_path, agent_cfg, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool, code in (("poetry", 1), ("uv", 0)):
        script = bin_dir / tool
        script.write_text(
            f'#!/bin/sh\necho "$VIRTUAL_ENV" > "{tmp_path}/{tool}.env"\nexit {code}\n'
        )
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    root = write_project(tmp_path / "proj", {"app.py": "x = 1\n"})
    ws, _ = prepare_workspace(root, tmp_path / "ws", agent_cfg["core"]["sandbox"])
    agent_cfg["core"]["agents"]["install"] = "auto"
    rt = Runtime(ws, agent_cfg, None, tmp_path / "out")
    plan = {"tool": "poetry", "steps": [["poetry", "install"]], "fallback": [["uv", "sync"]]}
    rt.brief = {"install_plan": plan}
    info = environment.prepare(rt)
    venv = tmp_path / "out" / environment.VENV
    assert (tmp_path / "poetry.env").read_text().strip() == str(venv)  # the tool saw the venv
    assert info["install"] == "installed into .cs_venv (pip (fallback), next to the workspace)"
    assert ws.python == str(venv / "bin" / "python") and "VIRTUAL_ENV" not in ws.extra_env


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
