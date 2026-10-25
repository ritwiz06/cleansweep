"""The live page copies run_sweep's steps; this catches the two drifting apart."""

from app.live_runner import run_live
from cleansweep.workflow import run_sweep


def by_status(report, status: str) -> set[str]:
    return {r.item_id for r in report.results if r.status == status}


def test_live_runner_matches_run_sweep(toy_repo, cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("CLEANSWEEP_JUDGE_MODE", "off")
    workflow = run_sweep(toy_repo, cfg, method="cleansweep")
    live, _ = run_live(toy_repo, cfg, "cleansweep", "off", run_id="drift", out_dir=tmp_path)
    for status in ("kept", "repaired", "rolled_back", "skipped"):
        assert by_status(live, status) == by_status(workflow, status), status
    assert by_status(workflow, "kept")
    for key in ("test_runs", "lines_removed", "files_removed", "n_checks", "items_total"):
        assert live.stats[key] == workflow.stats[key], key
    assert live.stats["final_diff"] == workflow.stats["final_diff"]
