import json
import os
import shutil

from cleansweep.runlog import (
    compare_reports,
    fold,
    list_runs,
    load_report,
    outcome_score,
    read_events,
)
from tests.conftest import FIXTURES


def test_read_events_skips_a_half_written_line(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"t": 0, "kind": "run_start"}\n{"t": 1, "kin')
    assert [e["kind"] for e in read_events(path)] == ["run_start"]
    assert read_events(tmp_path / "missing.jsonl") == []


def test_fold_tracks_stages_and_results():
    events = [
        {"t": 0.0, "kind": "run_start", "run_id": "r"},
        {"t": 0.1, "kind": "stage_start", "stage": "open"},
        {"t": 0.2, "kind": "stage_done", "stage": "open", "seconds": 0.1},
        {"t": 0.3, "kind": "stage_start", "stage": "guard"},
        {"t": 0.9, "kind": "stage_done", "stage": "guard", "seconds": 0.6, "results": []},
        {"t": 1.0, "kind": "error", "message": "boom"},
    ]
    state = fold(events)
    assert state["stages"] == {"open": "done", "guard": "done"}
    assert state["current"] is None and state["error"] == "boom" and state["t"] == 1.0


def test_list_runs_newest_first(tmp_path):
    for name, mtime in (("old", 1_000), ("new", 2_000)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "events.jsonl").write_text("")
        os.utime(tmp_path / name, (mtime, mtime))
    assert [p.name for p in list_runs(tmp_path)] == ["new", "old"]


def test_outcome_score_and_compare_reports(tmp_path):
    report = load_report(FIXTURES / "sample_report.json")
    score = outcome_score(report, FIXTURES / "toy_repo_expected.json")
    assert score["total"] == 13 and 0 < score["hits"] <= 13
    shutil.copy(FIXTURES / "sample_report.json", tmp_path / "a.json")
    (tmp_path / "a.txt").write_text("hidden checks: " + json.dumps({"behavior_changed": False}))
    (tmp_path / "notes.json").write_text("[]")
    table = compare_reports(tmp_path)
    assert list(table["run"]) == ["a"] and not table.loc[0, "hidden changed"]
