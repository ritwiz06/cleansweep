import json
import types

import pytest

from app.live_runner import (
    STAGES,
    EventLog,
    fold,
    list_runs,
    logged_check_fn,
    read_events,
    replay,
    run_live,
)
from cleansweep.core.io import load_json
from cleansweep.core.models import CleanupItem, CodeUnit, EditResult, SweepReport
from cleansweep.llm import FakeLLM
from cleansweep.reviewer.detectors import item_id
from cleansweep.scheduler import apply_with_bisection


def test_event_log_round_trip(tmp_path):
    seen = []
    log = EventLog(tmp_path / "run" / "events.jsonl", on_event=seen.append)
    log.emit("run_start", run_id="r1")
    log.emit("stage_done", stage="open", seconds=0.1)
    events = read_events(tmp_path / "run" / "events.jsonl")
    assert [e["kind"] for e in events] == ["run_start", "stage_done"]
    assert events == seen
    assert events[0]["t"] <= events[1]["t"]


def test_read_events_skips_a_half_written_line(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"t": 0, "kind": "run_start"}\n{"t": 1, "kin')
    assert [e["kind"] for e in read_events(path)] == ["run_start"]
    assert read_events(tmp_path / "missing.jsonl") == []


def test_replay_keeps_order_and_scales_time():
    events = [
        {"t": 0.0, "kind": "a"},
        {"t": 2.0, "kind": "b"},
        {"t": 2.0, "kind": "c"},
        {"t": 10.0, "kind": "d"},
    ]
    slept = []
    frames = list(replay(events, speed=4.0, tick=0.5, sleep=slept.append))
    counts = [n for _, n in frames]
    assert counts == sorted(counts) and counts[-1] == len(events)
    clocks = [c for c, _ in frames]
    assert clocks == sorted(clocks) and clocks[-1] == 10.0
    assert sum(slept) == pytest.approx(10.0 / 4.0)
    assert 3 in counts  # b and c share a timestamp, so they arrive together


class FakeGuard:
    def __init__(self, bad: set[str]):
        self.bad = bad
        self._results = {}

    def check_batch(self, batch):
        ok = not any(i.item_id in self.bad for i in batch)
        for i in batch:
            self._results[i.item_id] = EditResult(i.item_id, "kept" if ok else "rolled_back")
        return ok

    def results(self):
        return list(self._results.values())


def item(n: int) -> CleanupItem:
    return CleanupItem(
        f"i{n}", CodeUnit("m.py", "function", f"f{n}"), "dead_code", "delete_unit", "safe", "r"
    )


def test_bisection_splits_show_up_as_events(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    ws = types.SimpleNamespace(test_runs=0, base="b", diff_stats=lambda since: {"lines_removed": 3})
    check = logged_check_fn(FakeGuard(bad={"i2"}), ws, log)
    out = apply_with_bisection([[item(n) for n in range(4)]], check)
    assert out["rejected"] == ["i2"]
    results = [e for e in read_events(tmp_path / "events.jsonl") if e["kind"] == "batch_result"]
    assert [r["result"] for r in results] == [
        "split in half",
        "kept",
        "split in half",
        "rolled back",
        "kept",
    ]
    state = fold(read_events(tmp_path / "events.jsonl"))
    assert len(state["batches"]) == out["n_checks"] == 5
    assert state["kept"] == 3 and state["rolled_back"] == 1
    assert state["batches"][0]["items"] == ["i0", "i1", "i2", "i3"]


def test_fold_tracks_stages_and_the_judge():
    events = [
        {
            "t": 0,
            "kind": "run_start",
            "run_id": "r",
            "target": "x",
            "method": "cleansweep",
            "judge_mode": "gatekeeper",
        },
        {"t": 0, "kind": "stage_start", "stage": "open"},
        {"t": 1, "kind": "stage_done", "stage": "open", "seconds": 1},
        {"t": 1, "kind": "stage_start", "stage": "plan"},
        {"t": 2, "kind": "llm_start", "n": 1},
    ]
    state = fold(events)
    assert state["stages"] == {"open": "done", "plan": "running"}
    assert state["current"] == "plan" and state["current_since"] == 1
    assert state["llm"] == [{"n": 1, "start": 2, "seconds": None}]


def test_live_run_on_the_toy_repo(toy_repo, cfg, tmp_path):
    trap = item_id("shopcart/storage.py::_safe_round", "duplicate")
    cfg["llm_client"] = FakeLLM(
        {
            "cleanup plan": json.dumps(
                [
                    {
                        "item_id": trap,
                        "decision": "keep",
                        "reason": "Rounds differently.",
                        "confidence": 0.9,
                    }
                ]
            )
        }
    )
    report, run_dir = run_live(
        toy_repo, cfg, judge_mode="gatekeeper", run_id="t1", out_dir=tmp_path
    )
    events = read_events(run_dir / "events.jsonl")
    done = [e["stage"] for e in events if e["kind"] == "stage_done"]
    assert done == STAGES
    assert any(e["kind"] == "llm_start" for e in events)
    state = fold(events)
    assert state["hidden"]["behavior_changed"] is False
    assert state["kept"] == report.stats["items_kept"] == 10
    assert len(state["batches"]) == report.stats["n_checks"]
    assert load_json(SweepReport, run_dir / "report.json").stats["items_kept"] == 10
    assert list_runs(tmp_path) == [run_dir]


def test_capture_logs_puts_cleansweep_logs_in_the_events(tmp_path):
    import logging

    from app.live_runner import capture_logs

    log = EventLog(tmp_path / "events.jsonl")
    with capture_logs(log):
        logging.getLogger("cleansweep.reviewer.overengineering").info("dropped a finding")
        logging.getLogger("other").info("not ours")
    logging.getLogger("cleansweep.reviewer").info("after the run")
    events = read_events(tmp_path / "events.jsonl")
    assert [e["message"] for e in events] == ["dropped a finding"]
    assert fold(events)["logs"][0]["logger"] == "cleansweep.reviewer.overengineering"
