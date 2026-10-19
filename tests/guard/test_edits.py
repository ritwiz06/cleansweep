from pathlib import Path

from cleansweep.core.models import CleanupItem, CodeUnit
from cleansweep.guard import apply_edit


def item(path, kind, action, name=None, line=None, patch=None):
    return CleanupItem(
        "x", CodeUnit(path, kind, name, line), "other", action, "safe", "r", patch=patch
    )


def read(ws, path):
    return (Path(ws.path) / path).read_text()


def test_delete_file_goes_to_quarantine(toy_ws):
    it = item("debug_cart.py", "file", "delete_file")
    assert apply_edit(toy_ws, it)
    assert not (Path(toy_ws.path) / "debug_cart.py").exists()
    assert list(Path(toy_ws.quarantine_dir).rglob("debug_cart.py"))


def test_delete_unit(toy_ws):
    assert apply_edit(
        toy_ws, item("shopcart/utils.py", "function", "delete_unit", "format_money_v2")
    )
    text = read(toy_ws, "shopcart/utils.py")
    assert "format_money_v2" not in text and "def slugify" in text


def test_remove_import(toy_ws):
    assert apply_edit(toy_ws, item("shopcart/cart.py", "import", "remove_import", "os", 1))
    assert not read(toy_ws, "shopcart/cart.py").startswith("import os")


def test_remove_dependency(toy_ws):
    assert apply_edit(
        toy_ws, item("requirements.txt", "dependency", "remove_dependency", "requests")
    )
    assert "requests" not in read(toy_ws, "requirements.txt")


def test_format(toy_ws):
    assert apply_edit(toy_ws, item("shopcart/pricing.py", "file", "format"))
    assert "TAX_RATE = 0.08" in read(toy_ws, "shopcart/pricing.py")


def test_report_only_does_nothing(toy_ws):
    assert not apply_edit(toy_ws, item("shopcart/storage.py", "function", "report_only"))
