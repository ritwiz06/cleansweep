import dataclasses

from cleansweep.core import models
from cleansweep.core.io import from_dict, load_json, save_json, to_dict
from tests.conftest import FIXTURES


def test_sample_report_round_trip(tmp_path):
    report = load_json(models.SweepReport, FIXTURES / "sample_report.json")
    assert isinstance(report.plan.items[0].unit, models.CodeUnit)
    save_json(report, tmp_path / "r.json")
    assert load_json(models.SweepReport, tmp_path / "r.json") == report


def test_every_dataclass_round_trips():
    samples = [
        models.Task("i", "r", "c", "p", "t", ["a"], ["b"], "1"),
        models.AgentPatch("i", "agent_a", "diff", True, ["h"]),
        models.RepoRef("aidev:o/n", "u"),
        models.CommitEvent("s", "2026-01-01T00:00:00Z", True, "agent_a", 3, ["f.py"]),
        models.RunResult(False, 1, 2, failed_ids=["x"]),
        models.DiffOutcome(False, 3, 1, ["m"]),
        models.EditResult("id", "kept", models.RunResult(True), True, models.DiffOutcome(True)),
    ]
    for obj in samples:
        assert dataclasses.is_dataclass(obj)
        assert from_dict(type(obj), to_dict(obj)) == obj


def test_code_unit_key():
    assert models.CodeUnit("a.py", "file").key == "a.py"
    assert models.CodeUnit("a.py", "function", "C.f").key == "a.py::C.f"
