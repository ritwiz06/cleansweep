from pathlib import Path

import pytest

from cleansweep.agents.runners import detect, runner_of

from .conftest import write_project

CASE = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n"
PLAIN = "def test_a():\n    assert True\n"


@pytest.mark.parametrize(
    ("files", "source"),
    [
        ({"pytest.ini": "[pytest]\n"}, "pytest settings in pytest.ini"),
        ({"pyproject.toml": "[tool.pytest.ini_options]\n"}, "pytest settings in pyproject.toml"),
        ({"setup.cfg": "[tool:pytest]\n"}, "pytest settings in setup.cfg"),
        ({"tests/conftest.py": "", "tests/test_a.py": CASE}, "conftest.py"),
        ({"tests/test_a.py": PLAIN}, "test files in pytest style"),
    ],
)
def test_pytest_from_its_settings_or_the_test_files(tmp_path, files, source):
    found = detect(write_project(tmp_path, files))
    assert found["runner"] == "pytest" and found["source"] == source


def test_unittest_only_test_files_discover_from_their_folder(tmp_path):
    root = write_project(tmp_path / "a", {"tests/__init__.py": "", "tests/test_a.py": CASE})
    found = detect(root)
    assert found["runner"] == "unittest" and found["source"].endswith("all unittest.TestCase")
    assert (found["start"], found["top"], found["pattern"]) == ("tests", ".", "test*.py")
    plain_folder = detect(write_project(tmp_path / "b", {"test/a_test.py": CASE}))
    assert (plain_folder["start"], plain_folder["top"]) == ("test", "test")
    assert plain_folder["pattern"] == "*test*.py"


def test_tox_and_nox_give_the_command_they_run(tmp_path):
    tox = "[tox]\nenvlist = py311\n\n[testenv]\ncommands =\n    pytest {posargs} tests\n"
    found = detect(write_project(tmp_path / "a", {"tox.ini": tox, "tests/test_a.py": CASE}))
    assert found["runner"] == "pytest" and found["paths"] == ["tests"]
    assert found["source"] == "tox.ini [testenv] runs `pytest {posargs} tests`"
    unit = "[testenv]\ncommands = python -m unittest discover -s tests -p 'test_*.py'\n"
    found = detect(write_project(tmp_path / "b", {"tox.ini": unit, "tests/test_a.py": CASE}))
    assert found["runner"] == "unittest" and found["start"] == "tests"
    assert found["pattern"] == "test_*.py" and found["source"].startswith("tox.ini [testenv]")
    nox = (
        "import nox\n\n\n@nox.session\ndef lint(session):\n    session.run('ruff', 'check')\n\n\n"
        "@nox.session\ndef tests(session):\n    session.run('pytest', 'tests', *session.posargs)\n"
    )
    found = detect(write_project(tmp_path / "c", {"noxfile.py": nox, "tests/test_a.py": PLAIN}))
    assert found["runner"] == "pytest" and found["paths"] == ["tests"]
    assert found["source"] == "noxfile.py session tests runs `pytest tests`"


def test_a_makefile_test_target(tmp_path):
    runs_pytest = "test:\n\t@$(PYTHON) -m pytest tests -q\n"
    root = write_project(tmp_path / "a", {"Makefile": runs_pytest, "tests/test_a.py": PLAIN})
    assert detect(root)["paths"] == ["tests"]
    own = "lint:\n\truff check .\n\ntest:\n\t./run_tests.sh\n"
    found = detect(write_project(tmp_path / "b", {"Makefile": own, "check_a.py": "x = 1\n"}))
    assert found["runner"] == "command" and found["argv"] == ["make", "test"]


def test_no_tests_and_the_wrappers_runner_of_understands(tmp_path):
    assert detect(write_project(tmp_path, {"app.py": "x = 1\n"}))["runner"] == "none"
    (tmp_path / "tests").mkdir()
    for line in (
        "coverage run --branch -m pytest tests",
        "poetry run pytest tests",
        "PYTHONPATH=. python3 -m pytest tests",
    ):
        assert runner_of(line, Path(tmp_path))["paths"] == ["tests"], line
    assert runner_of("ruff check .", Path(tmp_path)) is None
    assert runner_of("pytest 'unclosed", Path(tmp_path)) is None
