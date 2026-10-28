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


def test_guard_strength_table_and_false_alarms():
    import pandas as pd

    from app.loaders import false_alarms, guard_strength_table

    rows = pd.DataFrame(
        [
            ["t1", "mutation", "runner", 39, 36, 30, 6],
            ["t1", "false_alarm", "runner", 10, 0, 0, 0],
        ],
        columns=["target_set", "experiment", "probe_mode", "n", "caught"]
        + ["caught_by_tests", "caught_by_probes"],
    )
    table = guard_strength_table(rows)
    assert table.iloc[0][["caught", "by tests", "only by probes"]].tolist() == ["36 / 39", 30, 6]
    assert table.iloc[0]["experiment"] == "mutants"
    assert false_alarms(rows).iloc[0]["false alarms / checks"] == "0 / 10"
    old = rows.drop(columns=["probe_mode"])  # before probe modes, every run was direct
    assert set(guard_strength_table(old)["probe mode"]) == {"direct"}


def test_rules_funnel_and_labels(tmp_path):
    import pandas as pd

    from app.loaders import funnel_stages, load_csv, repos_label, top_rules

    rules = pd.DataFrame(
        {"antecedents": ["a", "b", "c"], "consequents": ["x", "y", "z"]}
        | {"support": [0.1, 0.3, 0.2], "confidence": [0.5, 0.5, 0.5], "lift": [1.5, 2.0, 2.0]}
    )
    assert top_rules(rules, 2).antecedents.tolist() == ["b", "c"]
    funnel = pd.DataFrame(
        {"stage": ["sampled", "runnable", "dropped: install failed"], "count": [120, 21, 35]}
        | {"note": ["", "", ""]}
    )
    stages, reasons = funnel_stages(funnel)
    assert stages.stage.tolist() == ["sampled", "runnable"]
    assert reasons.iloc[0].tolist() == ["install failed", 35]
    assert load_csv("missing.csv", tmp_path) is None
    assert repos_label(20, 1) == "20 of 21 runnable repos (1 excluded)"
    assert repos_label(20) == "20 runnable repos"


def test_result_pages_render():
    from streamlit.testing.v1 import AppTest

    from tests.conftest import FIXTURES

    pages = FIXTURES.parents[1] / "app" / "pages"
    for name in ("2_Scheduler.py", "3_Baselines.py", "4_Data.py", "5_Guard.py"):
        at = AppTest.from_file(str(pages / name), default_timeout=60).run()
        assert not at.exception, (name, [e.value for e in at.exception])
