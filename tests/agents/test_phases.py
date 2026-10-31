import pytest

from cleansweep.agents.events import EventLog
from cleansweep.agents.phases import PhaseError, PhaseMachine


def test_phases_go_forward_in_order():
    machine = PhaseMachine()
    for phase in [
        "BASELINE",
        "AUDIT",
        "INVESTIGATE",
        "PLAN",
        "EXECUTE",
        "FINAL_VERIFY",
        "REPORT",
        "DONE",
    ]:
        machine.go(phase, "next")
    assert machine.order()[0] == "ONBOARD" and machine.order()[-1] == "DONE"
    assert set(machine.seconds()) == set(machine.order())


def test_skipping_ahead_is_only_allowed_to_report():
    machine = PhaseMachine()
    with pytest.raises(PhaseError):
        machine.go("PLAN", "skip")
    machine.go("REPORT", "nothing to do")
    assert machine.phase == "REPORT"


def test_steps_back_are_limited(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    machine = PhaseMachine(log)
    machine.go("BASELINE", "brief ready")
    machine.go("ONBOARD", "the test command failed")
    with pytest.raises(PhaseError):
        machine.go("ONBOARD", "again")  # ONBOARD is where we are
    machine.go("BASELINE", "brief revised")
    with pytest.raises(PhaseError):
        machine.go("ONBOARD", "a second time")
    for phase in ["AUDIT", "INVESTIGATE", "PLAN", "EXECUTE"]:
        machine.go(phase, "next")
    machine.go("PLAN", "rollback")
    machine.go("EXECUTE", "replanned")
    machine.go("PLAN", "rollback")
    machine.go("EXECUTE", "replanned")
    assert not machine.can_go_back("PLAN")
    with pytest.raises(PhaseError):
        machine.go("PLAN", "a third time")
    backs = [
        e["payload"] for e in log.events if e["kind"] == "phase_change" and e["payload"]["back"]
    ]
    assert [b["to"] for b in backs] == ["ONBOARD", "PLAN", "PLAN"]
