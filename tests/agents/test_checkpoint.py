import json

import pytest

from cleansweep.agents import checkpoint, clean_project, engineer, tester
from cleansweep.agents.events import read_events
from cleansweep.agents.run import Interrupted, resume_project

from .conftest import tree_hash


def _interrupt(monkeypatch, module, name: str, on_call: int) -> None:
    """Make module.name raise KeyboardInterrupt once, on its on_call-th call."""
    real, calls = getattr(module, name), []

    def once(*args, **kwargs):
        calls.append(1)
        if len(calls) == on_call:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, once)


def test_an_interrupted_run_resumes_from_its_last_package(mini, agent_cfg, tmp_path, monkeypatch):
    whole = clean_project(str(mini), agent_cfg, out=str(tmp_path / "whole"), use_llm=False)
    before = tree_hash(mini)
    out = tmp_path / "out"
    _interrupt(monkeypatch, engineer, "apply", on_call=2)
    with pytest.raises(Interrupted) as stop:
        clean_project(str(mini), agent_cfg, out=str(out), use_llm=False)
    assert stop.value.out == out and tree_hash(mini) == before
    report = (out / "CLEANUP_REPORT.md").read_text()
    assert "**Result: stopped: interrupted, nothing applied.**" in report
    assert f"cleansweep clean --resume {out}" in report
    saved = checkpoint.load(out)
    assert saved["phase"] == "EXECUTE" and saved["state"]["current"] == 1
    n_events = len(read_events(out / "events.jsonl"))
    result = resume_project(str(out))
    summary = result["summary"]
    assert summary["verdict"] == "everything runs" and summary["resumed"] == ["EXECUTE"]
    assert summary["applied"] == whole["summary"]["applied"]
    assert [p["status"] for p in result["report"].stats["agentic"]["packages"]] == [
        p["status"] for p in whole["report"].stats["agentic"]["packages"]
    ]
    events = read_events(out / "events.jsonl")
    assert len(events) > n_events and len({e["id"] for e in events}) == len(events)
    assert "Resumed after an interruption, at EXECUTE." in (out / "CLEANUP_REPORT.md").read_text()
    assert checkpoint.load(out)["phase"] == "DONE" and tree_hash(mini) == before
    with pytest.raises(ValueError, match="has finished"):
        resume_project(str(out))


def test_a_run_cut_off_in_its_baseline_resumes_there(mini, agent_cfg, tmp_path, monkeypatch):
    out = tmp_path / "out"
    _interrupt(monkeypatch, tester, "baseline", on_call=1)
    with pytest.raises(KeyboardInterrupt):
        clean_project(str(mini), agent_cfg, out=str(out), use_llm=False, test_args=["-q"])
    assert checkpoint.load(out)["phase"] == "BASELINE"
    assert json.loads((out / "run.json").read_text())["test_args"] == ["-q"]
    monkeypatch.chdir(tmp_path)
    result = resume_project("out")  # the run id, found from the current folder
    assert result["summary"]["verdict"] == "everything runs"
    assert result["report"].stats["agentic"]["phases"][:3] == ["ONBOARD", "BASELINE", "AUDIT"]


def test_nothing_to_resume(tmp_path):
    with pytest.raises(FileNotFoundError, match="no run to resume"):
        resume_project(str(tmp_path / "none"))
    (tmp_path / "run.json").write_text(json.dumps({"path": "x"}))
    with pytest.raises(ValueError, match="before its first checkpoint"):
        resume_project(str(tmp_path))
