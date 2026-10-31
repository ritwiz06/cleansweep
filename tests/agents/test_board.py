import jsonschema
import pytest

from cleansweep.agents.board import AGENTS, MessageBoard
from cleansweep.agents.events import EventLog


def test_a_message_reaches_only_its_recipients():
    board = MessageBoard()
    board.post(
        "verdict",
        "investigator#1",
        {"item_id": "a", "decision": "safe", "reason": "r", "evidence": []},
    )
    board.post("task", "manager", {"goal": "write the brief"}, recipients=["explorer"])
    assert [m.type for m in board.inbox("planner")] == ["verdict"]
    assert [m.type for m in board.inbox("explorer")] == ["task"]
    assert board.inbox("engineer") == []
    assert board.hyperedges() == [
        ("investigator#1", ("manager", "planner")),
        ("manager", ("explorer",)),
    ]


def test_instances_read_their_role_inbox():
    board = MessageBoard()
    board.post(
        "candidates",
        "auditor",
        {"items": [{"item_id": "a", "unit": "x.py", "category": "dead_code", "lane": "safe"}]},
    )
    assert len(board.inbox("investigator#3")) == 1


def test_a_malformed_message_is_rejected():
    board = MessageBoard()
    with pytest.raises(jsonschema.ValidationError):
        board.post(
            "verdict",
            "investigator",
            {"item_id": "a", "decision": "maybe", "reason": "r", "evidence": []},
        )
    with pytest.raises(ValueError):
        board.post("gossip", "planner", {})
    with pytest.raises(ValueError):
        board.post("task", "manager", {"goal": "no one to send it to"})
    assert board.messages == []


def test_broadcast_sends_every_message_to_every_other_agent():
    board = MessageBoard(broadcast=True)
    board.post("lesson", "fixer", {"lesson_id": "L1", "pattern": {}, "reason": "r"})
    assert set(board.messages[0].recipients) == set(AGENTS) - {"fixer"}
    assert board.inbox("reporter")


def test_posting_logs_a_message_event_with_its_recipients(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    board = MessageBoard(log)
    board.post(
        "report", "reporter", {"files": ["CLEANUP_REPORT.md"]}, artifacts=["art:report:12345678"]
    )
    event = log.events[-1]
    assert event["kind"] == "message" and event["recipients"] == ["manager"]
    assert event["artifacts"] == ["art:report:12345678"] and event["squad"] == "development"
