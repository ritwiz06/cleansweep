from app.loaders import find_reports, load_report, plan_table, restore_command, slop_meter
from tests.conftest import FIXTURES


def test_falls_back_to_sample(tmp_path):
    assert find_reports(tmp_path) == [FIXTURES / "sample_report.json"]


def test_tables_from_sample():
    report = load_report(FIXTURES / "sample_report.json")
    table = plan_table(report)
    assert len(table) == len(report.plan.items)
    assert {"kept", "rolled_back", "skipped"} <= set(table["status"])
    meter = slop_meter(report)
    assert meter["cleaned"] + meter["open"] == len(report.plan.items)


def test_restore_command():
    assert restore_command(["quarantined at /q/a.py"], "a.py") == "cp '/q/a.py' 'a.py'"
    assert restore_command(["other"], "a.py") is None
