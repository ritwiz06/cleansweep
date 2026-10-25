"""Keep the live demo working: the app, its answer key, hidden tests and prepare script."""

import json
import subprocess
import sys
from pathlib import Path

from cleansweep.eval import run_hidden_checks
from cleansweep.reviewer import run_detectors

DEMO = Path(__file__).resolve().parents[2] / "demo"
APP = DEMO / "shop_app"


def test_demo_app_tests_pass():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=APP,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout
    assert "11 passed" in proc.stdout


def test_detectors_find_the_planted_items():
    expected = json.loads((DEMO / "shop_app_expected.json").read_text())["items"]
    items = {i.unit.key: i for i in run_detectors(str(APP))}
    for row in expected:
        assert row["key"] in items, row["key"]
        assert items[row["key"]].category == row["category"], row["key"]
        assert items[row["key"]].lane == row["expected_lane"], row["key"]


def test_hidden_checks_pass_on_the_untouched_app(cfg):
    hidden = run_hidden_checks(str(APP), "", cfg)
    assert hidden["available"] and hidden["behavior_changed"] is False
    assert hidden["hidden_before"]["passed"] == 3


def test_prepare_demo_with_feature(tmp_path):
    dest = tmp_path / "demo"
    out = subprocess.run(
        ["bash", str(DEMO / "prepare_demo.sh"), "--with-feature", str(dest)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    app = Path(out)
    assert app == dest / "shop_app"
    assert (dest / "shop_app_hidden").is_dir() and (dest / "shop_app_expected.json").exists()
    assert "_print_low_stock" in (app / "bookshelf" / "inventory.py").read_text()
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=app, capture_output=True, text=True
    ).stdout
    assert len(log.splitlines()) == 2
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=app,
        capture_output=True,
        text=True,
    )
    assert "12 passed" in proc.stdout
    keys = {i.unit.key for i in run_detectors(str(app))}
    assert "bookshelf/inventory.py::_print_low_stock" in keys
