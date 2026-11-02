"""The live page runs run_sweep itself; its events must tell the same story as the report."""

from cleansweep.live import STAGES, fold, read_events, run_live
from cleansweep.workflow import run_sweep


def test_events_match_the_report(toy_repo, cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("CLEANSWEEP_JUDGE_MODE", "off")
    report, run_dir = run_live(toy_repo, cfg, "cleansweep", "off", run_id="ev", out_dir=tmp_path)
    events = read_events(run_dir / "events.jsonl")
    assert [e["stage"] for e in events if e["kind"] == "stage_done"] == STAGES
    state = fold(events)
    assert state["statuses"] == {r.item_id: r.status for r in report.results}
    checks = [e for e in events if e["kind"] == "batch_result"]
    assert len(checks) == len(state["batches"]) == report.stats["n_checks"]
    assert checks[-1]["test_runs"] == report.stats["test_runs"]
    assert checks[-1]["lines_removed"] == report.stats["lines_removed"]
    assert {i["item_id"] for i in state["items"]} == {i.item_id for i in report.plan.items}
    # the same sweep without a callback gives the same report
    plain = run_sweep(toy_repo, cfg, method="cleansweep")
    assert plain.stats["final_diff"] == report.stats["final_diff"]
    assert {r.item_id: r.status for r in plain.results} == state["statuses"]


def test_on_event_reports_each_step_and_check(toy_repo, cfg, monkeypatch):
    monkeypatch.setenv("CLEANSWEEP_JUDGE_MODE", "off")
    seen = []
    report = run_sweep(toy_repo, cfg, on_event=lambda name, payload: seen.append((name, payload)))
    steps = [n for n, _ in seen if n not in ("check_start", "check")]
    assert steps == ["open", "analyze", "plan", "rank", "batch", "baseline", "guard", "report"]
    assert sum(n == "check" for n, _ in seen) == report.stats["n_checks"]
    assert dict(seen)["guard"]["stats"]["items_kept"] == report.stats["items_kept"]
