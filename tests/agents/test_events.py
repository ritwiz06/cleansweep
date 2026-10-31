import pytest

from cleansweep.agents.events import EventLog, read_events


def test_v2_events_have_the_schema_fields_and_go_to_the_file(tmp_path):
    seen = []
    log = EventLog(
        tmp_path / "events.jsonl",
        run_id="r1",
        on_event=seen.append,
        redact=lambda s: s.replace("pw", "**"),
    )
    log.phase = "AUDIT"
    first = log.emit(
        "tool_call", agent="auditor", payload={"tool": "run_detectors", "args": {"pw": "pw"}}
    )
    log.emit(
        "tool_result",
        agent="auditor",
        parent=first["id"],
        payload={"result": "pw found"},
        artifacts=["art:x:1"],
    )
    events = read_events(tmp_path / "events.jsonl")
    assert events == seen
    keys = {
        "v",
        "id",
        "parent",
        "t",
        "ts",
        "run_id",
        "agent",
        "squad",
        "phase",
        "kind",
        "recipients",
        "artifacts",
        "payload",
    }
    assert all(keys <= set(e) for e in events)
    assert (
        events[1]["parent"] == events[0]["id"]
        and events[0]["squad"] == "research"
        and events[0]["phase"] == "AUDIT"
    )
    assert events[1]["payload"]["result"] == "** found"


def test_unknown_kinds_are_refused(tmp_path):
    with pytest.raises(ValueError):
        EventLog().emit("gossip")


def test_v1_hook_gets_v1_events():
    got = []
    EventLog(v1_hook=lambda name, payload: got.append(name)).v1("baseline", {"test_runs": 1})
    assert got == ["baseline"]
