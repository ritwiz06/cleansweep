import importlib.util
import sys
from pathlib import Path

from cleansweep.core.io import load_json
from cleansweep.core.models import SweepReport

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v1"
FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


def load():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("self_sweep", SCRIPTS / "exp_self_sweep.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_copy_and_summary(tmp_path):
    self_sweep = load()
    copy = self_sweep.copy_at("HEAD", tmp_path)
    assert (copy / "pyproject.toml").exists() and not (copy / ".git").exists()
    text = self_sweep.summary(load_json(SweepReport, FIXTURES / "sample_report.json"))
    assert "judge vetoes" in text and "lines removed" in text


def test_table_row_counts_items_and_checks():
    self_sweep = load()
    row = self_sweep.row("gatekeeper", load_json(SweepReport, FIXTURES / "sample_report.json"))
    assert row["mode"] == "gatekeeper" and row["items"] == row["safe"] + row["suggest"]
    assert row["kept"] >= 0 and row["minutes"] >= 0
