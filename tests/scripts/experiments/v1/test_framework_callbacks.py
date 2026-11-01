import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v1"


def load(name):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _item(item_id, name, category="dead_code", lane="safe"):
    return {
        "item_id": item_id,
        "unit": {"path": "shotgun/ui.py", "kind": "function", "name": name},
        "category": category,
        "action": "delete_unit",
        "lane": lane,
        "safe_score": 0.7,
        "evidence": [],
    }


def test_callbacks_need_a_framework_base_and_a_framework_name(tmp_path):
    fc = load("exp_framework_callbacks")
    (tmp_path / "shotgun").mkdir()
    (tmp_path / "shotgun" / "base.py").write_text(
        "from textual.screen import Screen\nclass BaseScreen(Screen):\n    pass\n"
    )
    (tmp_path / "shotgun" / "ui.py").write_text(
        "import json\n"
        "from .base import BaseScreen\n"
        "class Welcome(BaseScreen):\n"
        "    def compose(self): ...\n"
        "    def on_mount(self): ...\n"
        "    def helper(self): ...\n"
        "class Plain(json.JSONEncoder):\n"
        "    def on_mount(self): ...\n"
    )
    classes, methods = fc.class_index(tmp_path)
    assert fc.framework_of("Welcome", classes) == "textual"  # through the project's BaseScreen
    assert fc.framework_of("Plain", classes) is None  # a standard-library base
    names = ["Welcome.compose", "Welcome.on_mount", "Welcome.helper", "Plain.on_mount"]
    kinds = [fc.kind(_item("x", n), classes, methods) for n in names]
    assert kinds == ["callback", "callback", "", ""]


def test_rebuilt_checks_bisect_failing_batches():
    fc = load("exp_framework_callbacks")
    report = {
        "plan": {"items": [_item(k, f"C.m{k}") for k in "abcd"]},
        "results": [
            {"item_id": k, "status": "rolled_back" if k == "c" else "kept", "notes": "tests failed"}
            for k in "abcd"
        ],
    }
    failed, n = fc.rebuilt_checks(report)
    # [a b c d] fails -> [a b] passes, [c d] fails -> [c] fails, [d] passes
    assert n == 5
    assert failed == [(["c"], True)] * 3
