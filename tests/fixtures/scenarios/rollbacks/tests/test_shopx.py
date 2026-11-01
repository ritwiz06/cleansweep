import importlib

from shopx.app import export
from shopx.cart import count
from shopx.money import cents
from shopx.report import total
from shopx.units import grams


def test_export():
    assert export("csv", ["a", "b"]) == "a,b"


def test_legacy_rate_still_loads():
    assert importlib.import_module("shopx." + "legacy" + "_old").RATE == 0.2


def test_total_reports(capsys):
    assert total([1, 2]) == 3
    assert "debug: total 3" in capsys.readouterr().out


def test_small():
    assert count([1]) == 1 and cents(1.5) == 150 and grams(2) == 2000
