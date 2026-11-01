from pathlib import Path

import pytest

from cleansweep.core.models import CleanupItem, CodeUnit
from cleansweep.guard import ui_check
from cleansweep.sandbox import open_workspace

pytest.importorskip("textual")

SCREENS = """from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label, Static


class HomeScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Label("Welcome home")


class Banner(Static):
    def __init__(self, title: str):
        super().__init__(f"== {title} ==")


class OldPanel(Static):
    pass
"""


@pytest.fixture
def tui_ws(tmp_path, sandbox_cfg):
    src = tmp_path / "proj"
    (src / "tuiapp").mkdir(parents=True)
    (src / "tuiapp" / "__init__.py").write_text("")
    (src / "tuiapp" / "screens.py").write_text(SCREENS)
    (src / "tuiapp" / "core.py").write_text("def add(a, b):\n    return a + b\n")
    (src / "tests").mkdir()
    (src / "tests" / "test_screens.py").write_text("import textual\n")
    ws = open_workspace(str(src), sandbox_cfg)
    yield ws
    ws.close()


def item(path: str, name: str | None, action: str) -> CleanupItem:
    unit = CodeUnit(path, "class" if name else "file", name)
    return CleanupItem("i", unit, "dead_code", action, "safe", "unused")


def test_textual_modules_leave_out_tests_and_other_modules(tui_ws):
    assert ui_check.textual_modules(tui_ws.path) == ["tuiapp.screens"]


def test_snapshot_mounts_screens_and_widgets_and_cleans_up(tui_ws):
    snap = ui_check.snapshot(tui_ws, ["tuiapp.screens"])
    classes = snap["classes"]
    assert set(classes) == {
        "tuiapp.screens.HomeScreen",
        "tuiapp.screens.Banner",
        "tuiapp.screens.OldPanel",
    }
    assert "Welcome home" in classes["tuiapp.screens.HomeScreen"]["text"]
    assert "== example ==" in classes["tuiapp.screens.Banner"]["text"]  # placeholder argument
    assert not list(Path(tui_ws.path).glob("_probes/ui_*"))
    assert tui_ws._git("status", "--porcelain") == ""


def test_same_code_passes_and_changed_text_fails(tui_ws):
    base = ui_check.baseline(tui_ws, ["tuiapp.screens"])
    assert base["unstable"] == []
    same = ui_check.compare(base, ui_check.snapshot(tui_ws, base["modules"]), set())
    assert same["ok"] and same["classes"] == 3
    path = Path(tui_ws.path) / "tuiapp" / "screens.py"
    path.write_text(path.read_text().replace("Welcome home", "Welcome"))
    changed = ui_check.compare(base, ui_check.snapshot(tui_ws, base["modules"]), set())
    assert not changed["ok"]
    assert changed["changed"] == ["tuiapp.screens.HomeScreen"]


def test_a_class_the_package_deletes_is_removed_not_lost(tui_ws):
    base = ui_check.baseline(tui_ws, ["tuiapp.screens"])
    path = Path(tui_ws.path) / "tuiapp" / "screens.py"
    path.write_text(path.read_text().split("class OldPanel")[0])
    after = ui_check.snapshot(tui_ws, base["modules"])
    deleted = ui_check.deleted_names([item("tuiapp/screens.py", "OldPanel", "delete_unit")])
    assert ui_check.compare(base, after, deleted)["removed"] == ["tuiapp.screens.OldPanel"]
    assert ui_check.compare(base, after, deleted)["ok"]
    lost = ui_check.compare(base, after, set())
    assert not lost["ok"] and lost["lost"] == ["tuiapp.screens.OldPanel"]


def test_a_module_that_stops_importing_fails(tui_ws):
    base = ui_check.baseline(tui_ws, ["tuiapp.screens"])
    path = Path(tui_ws.path) / "tuiapp" / "screens.py"
    path.write_text("from tuiapp.missing import gone\n" + path.read_text())
    result = ui_check.compare(base, ui_check.snapshot(tui_ws, base["modules"]), set())
    assert result["broken"] == ["tuiapp.screens"]
    assert not result["ok"]
    deleted = ui_check.deleted_names([item("tuiapp/screens.py", None, "delete_file")])
    assert deleted == {"tuiapp.screens"}


def test_unstable_classes_are_left_out():
    snap = {"import_errors": {}, "classes": {"m.A": {"text": "1"}, "m.B": {"text": "x"}}}
    base = {"modules": ["m"], "snapshot": snap, "unstable": ["m.A"]}
    after = {"import_errors": {}, "classes": {"m.A": {"text": "2"}, "m.B": {"text": "x"}}}
    result = ui_check.compare(base, after, set())
    assert result["ok"] and result["classes"] == 1 and result["unstable"] == 1
