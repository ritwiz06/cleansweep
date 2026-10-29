import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "data_aidev_scope.py"


def load():
    spec = importlib.util.spec_from_file_location("data_aidev_scope", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scope_share_counts_agent_files_and_agent_lines_in_python_only():
    scope_script = load()
    py_lines = {"pkg/new.py": 30, "pkg/old.py": 60, "pkg/other.py": 10}
    scope = {
        "files_added": ["pkg/new.py", "README.md"],
        "lines": {"pkg/old.py": [1, 2, 3, 4, 5], "docs/a.md": [1, 2]},
    }
    assert scope_script.scope_share(py_lines, scope) == {
        "py_files": 3,
        "py_lines": 100,
        "agent_py_files": 1,
        "agent_file_lines": 30,
        "agent_changed_lines": 5,
        "share": 0.35,
    }
    assert scope_script.scope_share({}, {"files_added": [], "lines": {}})["share"] == ""


def test_items_outside_counts_plan_items_beyond_the_agent_files():
    scope_script = load()
    scope = {"files_added": ["pkg/new.py"], "lines": {"pkg/old.py": [3]}}
    items = [
        {"unit": {"path": "pkg/new.py"}},
        {"unit": {"path": "pkg/old.py"}},
        {"unit": {"path": "."}},  # tools_only's whole-repo ruff item
        {"unit": {"path": "examples/demo.py"}},
    ]
    assert scope_script.items_outside(items, scope) == 1
