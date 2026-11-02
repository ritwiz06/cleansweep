import json
import types

import pytest

from cleansweep.core.io import load_json
from cleansweep.core.models import CleanupItem, CodeUnit, EditResult, SweepReport
from cleansweep.live import (
    STAGES,
    EventLog,
    fold,
    list_runs,
    read_events,
    replay,
    run_live,
    translate,
)
from cleansweep.llm import FakeLLM
from cleansweep.reviewer.detectors import item_id
from cleansweep.scheduler import apply_with_bisection
from cleansweep.workflow.sweep import report_checks


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
    check = report_checks(FakeGuard(bad={"i2"}), ws, translate(log))
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

    from cleansweep.live import capture_logs

    log = EventLog(tmp_path / "events.jsonl")
    with capture_logs(log):
        logging.getLogger("cleansweep.reviewer.overengineering").info("dropped a finding")
        logging.getLogger("other").info("not ours")
    logging.getLogger("cleansweep.reviewer").info("after the run")
    events = read_events(tmp_path / "events.jsonl")
    assert [e["message"] for e in events] == ["dropped a finding"]
    assert fold(events)["logs"][0]["logger"] == "cleansweep.reviewer.overengineering"


def test_probe_outcome_reaches_the_batch_cards(toy_repo, cfg, tmp_path):
    probe = (
        "def make_cases():\n"
        "    from shopcart.storage import _safe_round\n"
        "    return [('tie', lambda: _safe_round(0.125))]\n"
    )
    reply = {"probes": [{"target": "shopcart/storage.py::_safe_round", "code": probe}]}
    cfg["llm_client"] = FakeLLM({"Target id": json.dumps(reply)})
    cfg["core"]["guard"]["probe_cache_dir"] = str(tmp_path / "probes")
    report, run_dir = run_live(toy_repo, cfg, judge_mode="advisory", run_id="p", out_dir=tmp_path)
    state = fold(read_events(run_dir / "events.jsonl"))
    caught = [b for b in state["batches"] if b.get("probes") and not b["probes"]["same"]]
    assert caught and any("_safe_round" in m for m in caught[-1]["probes"]["mismatches"])
    trap = item_id("shopcart/storage.py::_safe_round", "duplicate")
    assert state["statuses"][trap] == "rolled_back"
    assert state["hidden"]["behavior_changed"] is False


def test_shipped_recordings_replay_from_the_repository():
    from cleansweep.live import ROOT, shipped_runs

    changed = {}
    for run_dir in shipped_runs():
        state = fold(read_events(run_dir / "events.jsonl"))
        assert (ROOT / state["report"]).is_file()
        changed[run_dir.name] = state["hidden"]["behavior_changed"]
    assert list(changed)[0] == "20261030_demo_feature_advisory_v1"
    # before the probes existed, the near-duplicate trap got through
    assert changed == {
        "20261030_demo_feature_advisory_v1": False,
        "20261026_demo_feature_advisory_probes": False,
        "20261025_demo_feature_advisory": True,
    }
