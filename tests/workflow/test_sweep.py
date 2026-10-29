from cleansweep.core.io import load_json
from cleansweep.core.models import STATS_KEYS, SweepReport
from cleansweep.workflow import run_sweep


def test_real_sweep_on_toy_repo(toy_repo, toy_expected, cfg):
    report = run_sweep(toy_repo, cfg, method="cleansweep")
    status = {
        i.unit.key: r.status
        for i in report.plan.items
        for r in report.results
        if r.item_id == i.item_id
    }
    for row in toy_expected:
        if row["expected_lane"] == "safe" and row.get("trap") is None:
            assert status[row["key"]] == "kept", row["key"]
    assert status["shopcart/commands.py::cmd_export"] == "skipped"
    assert set(STATS_KEYS) <= set(report.stats)
    assert report.stats["files_removed"] == 3
    assert report.stats["scope"] == {"kind": "repo"}  # a local path: the whole repository


def test_no_batching_runs_more_tests(toy_repo, cfg):
    batched = run_sweep(toy_repo, cfg, method="cleansweep")
    single = run_sweep(toy_repo, cfg, method="no_batching")
    assert single.stats["test_runs"] > batched.stats["test_runs"]


def test_saves_report_when_run_id_given(toy_repo, cfg, tmp_path):
    cfg["run_id"] = "t1"
    cfg["core"]["out_dir"] = str(tmp_path / "raw")
    report = run_sweep(toy_repo, cfg)
    saved = list((tmp_path / "raw" / "t1").glob("*.json"))
    assert len(saved) == 1
    assert load_json(SweepReport, saved[0]).stats == report.stats


def test_stub_workflow(monkeypatch, toy_repo):
    monkeypatch.setenv("CLEANSWEEP_STUBS", "workflow")
    from cleansweep.workflow import stub

    report = stub.run_sweep(toy_repo, {}, method="no_ranker")
    assert report.repo_id == "local:toy_repo" and report.method == "no_ranker"
