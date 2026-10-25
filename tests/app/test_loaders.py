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


def test_find_reports_skips_json_that_is_not_a_report(tmp_path):
    import shutil

    shutil.copy(FIXTURES / "sample_report.json", tmp_path / "run.json")
    (tmp_path / "summary.json").write_text('[{"model": "m"}]')
    (tmp_path / "timing.json").write_text('{"calls": []}')
    assert find_reports(tmp_path) == [tmp_path / "run.json"]


def test_judge_decision_reads_the_last_judge_line():
    from app.loaders import judge_decision

    evidence = ["vulture: unused", "llm judge: keep (confidence 0.9)"]
    assert judge_decision(evidence) == ("keep", 0.9)
    assert judge_decision(["llm judge: remove (confidence None)"]) == ("remove", None)
    assert judge_decision(["no judge here"]) == ("-", None)


def test_outcome_score_against_the_answer_key():
    from app.loaders import outcome_score

    report = load_report(FIXTURES / "sample_report.json")
    score = outcome_score(report, FIXTURES / "toy_repo_expected.json")
    assert score["total"] == 13
    table = score["table"].set_index("unit")
    assert table.loc["shopcart/commands.py::cmd_export", "actual"] == "not_applied"
    assert table.loc["shopcart/commands.py::cmd_export", "match"]
    assert table.loc["debug_cart.py", "actual"] == "applied"


def test_compare_reports_reads_hidden_results_from_logs(tmp_path):
    import json
    import shutil

    from app.loaders import compare_reports

    shutil.copy(FIXTURES / "sample_report.json", tmp_path / "a.json")
    summary = {"behavior_changed": True, "visible_new_failures": 2}
    (tmp_path / "a.txt").write_text("table...\n\nhidden checks: " + json.dumps(summary) + "\n")
    shutil.copy(FIXTURES / "sample_report.json", tmp_path / "b.json")
    table = compare_reports(tmp_path).set_index("run")
    assert table.loc["a", "hidden changed"] is True
    assert table.loc["a", "visible broken"] == 2
    assert list(table.index) == ["a", "b"]
