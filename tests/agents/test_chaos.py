"""Chaos tests: faults injected into an offline clean. Whatever fails, the original is never
written to, the run ends with its report, and what it delivers breaks no test."""

import pytest

from cleansweep.agents import clean_project
from cleansweep.agents.scripted import ScriptedLLM, final, tool
from cleansweep.core.models import RunResult
from cleansweep.llm import LLMError
from cleansweep.sandbox.workspace import Workspace

from .conftest import tree_hash


class DownLLM(ScriptedLLM):
    """An endpoint that is down: every request times out."""

    def _reply(self, messages):
        super()._reply(messages)
        raise LLMError("APITimeoutError: Request timed out.")


def clean(project, cfg, tmp_path, **kwargs) -> dict:
    before = tree_hash(project)
    out = tmp_path / "out"
    result = clean_project(str(project), cfg, out=str(out), **kwargs)
    assert tree_hash(project) == before
    assert result["summary"]["final"]["new_failures"] == []
    assert (out / "report.json").exists() and (out / "CLEANUP_REPORT.md").exists()
    return result


@pytest.mark.parametrize(
    "llm", [DownLLM(), ScriptedLLM(default="no JSON here {")], ids=["down", "garbage"]
)
def test_an_llm_that_fails_on_every_request(mini, agent_cfg, tmp_path, llm):
    result = clean(mini, agent_cfg, tmp_path, llm=llm)
    assert result["summary"]["verdict"] in ("everything runs", "nothing applied")
    assert llm.calls  # the agents asked, and carried on without answers


def test_a_test_run_that_crashes_rolls_its_package_back(mini, agent_cfg, tmp_path, monkeypatch):
    real, runs = Workspace.run_tests, []

    def run_tests(self, test_paths=None, timeout=900):
        runs.append(1)
        if len(runs) == 4:  # the first package's tests, after three baseline runs
            self.test_runs += 1
            self.last_statuses = {}
            return RunResult(ok=False, errors=1, failed_ids=["<pytest exit 124>"], duration_s=0)
        return real(self, test_paths, timeout=timeout)

    monkeypatch.setattr(Workspace, "run_tests", run_tests)
    result = clean(mini, agent_cfg, tmp_path, use_llm=False)
    statuses = [p["status"] for p in result["report"].stats["agentic"]["packages"]]
    assert "rolled_back" in statuses and result["summary"]["verdict"] == "everything runs"


def test_a_tool_that_raises_is_an_observation(mini, agent_cfg, tmp_path, monkeypatch):
    from cleansweep.agents import tools

    def broken(rt, name, include_tests=True):
        raise OSError("disk read failed")

    monkeypatch.setattr(tools, "find_references", broken)
    llm = ScriptedLLM(
        [("legacy_alpha", [tool("find_references", {"name": "legacy_alpha"})])],
        default=final({"summary": "A shop.", "notes": []}),
    )
    result = clean(mini, agent_cfg, tmp_path, llm=llm)
    alpha = next(i for i in result["report"].plan.items if "legacy_alpha" in i.unit.key)
    assert alpha.lane != "safe"  # no usable evidence: never applied on the LLM's say-so
    sent = "\n".join(m["content"] for call in llm.calls for m in call)
    assert "error: OSError: disk read failed" in sent


def test_an_interrupted_run_leaves_the_original_alone(mini, agent_cfg, tmp_path, monkeypatch):
    from cleansweep.agents import engineer

    def interrupted(rt, pkg):
        raise KeyboardInterrupt

    monkeypatch.setattr(engineer, "apply", interrupted)
    before = tree_hash(mini)
    with pytest.raises(KeyboardInterrupt):
        clean_project(str(mini), agent_cfg, out=str(tmp_path / "out"), use_llm=False)
    assert tree_hash(mini) == before


VERDICTS = ("everything runs", "nothing applied", "not verified by tests", "not verified")


def ends_with_a_report(project, cfg, tmp_path, **kwargs) -> dict:
    """Any failure: the run returns, its report and report.json are written, the verdict is
    one of the fixed set, and the original is unchanged."""
    before = tree_hash(project)
    out = tmp_path / "out"
    result = clean_project(str(project), cfg, out=str(out), use_llm=False, **kwargs)
    verdict = result["summary"]["verdict"]
    assert verdict in VERDICTS or (
        verdict.startswith("stopped: ") and verdict.endswith(", nothing applied")
    )
    report = (out / "CLEANUP_REPORT.md").read_text()
    assert f"**Result: {verdict}.**" in report and (out / "report.json").exists()
    assert tree_hash(project) == before
    return result


def _raise(exc):
    def fail(*args, **kwargs):
        raise exc

    return fail


@pytest.mark.parametrize(
    ("target", "exc", "reason"),
    [
        ("cleansweep.agents.delivery._git", FileNotFoundError("git"), "FileNotFoundError: git"),
        ("cleansweep.agents.runtime.build_graph", SyntaxError("bad file"), "SyntaxError: bad"),
        ("cleansweep.agents.reporter.report_md", OSError("disk full"), "OSError: disk full"),
        ("cleansweep.agents.auditor.build_plan", OSError("lost"), "auditor failed: OSError"),
    ],
    ids=["missing git", "setup error", "reporter error", "agent error"],
)
def test_an_error_stops_the_run_with_a_report(
    mini, agent_cfg, tmp_path, monkeypatch, target, exc, reason
):
    monkeypatch.setattr(target, _raise(exc))
    result = ends_with_a_report(mini, agent_cfg, tmp_path)
    assert result["summary"]["verdict"].startswith(f"stopped: {reason}")


def test_a_test_command_that_fails_at_baseline(mini, agent_cfg, tmp_path):
    (mini / "pytest.ini").write_text("[pytest]\naddopts = --no-such-option\n")
    result = ends_with_a_report(mini, agent_cfg, tmp_path)
    assert result["summary"]["untested"]
    report = (tmp_path / "out" / "CLEANUP_REPORT.md").read_text()
    assert "No usable tests (the test command failed (<pytest exit 4>))" in report


def test_a_missing_dependency_leaves_no_test_passing(mini, agent_cfg, tmp_path):
    test = mini / "tests" / "test_shop.py"
    test.write_text("import cs_missing_dependency  # noqa\n" + test.read_text())
    result = ends_with_a_report(mini, agent_cfg, tmp_path)
    assert result["summary"]["untested"]
    assert result["report"].stats["agentic"]["baseline"]["reason"] == "no test passes"


def test_unparseable_files_and_a_notebook_only_folder(mini, agent_cfg, tmp_path):
    (mini / "shop" / "broken.py").write_text("def broken(:\n")
    (mini / "shop" / "latin.py").write_bytes(b"x = '\xe9'\n")
    assert ends_with_a_report(mini, agent_cfg, tmp_path / "a")["summary"]["applied"] > 0
    notebook = tmp_path / "nb"
    notebook.mkdir()
    (notebook / "analysis.ipynb").write_text('{"cells": [], "nbformat": 4}')
    result = ends_with_a_report(notebook, agent_cfg, tmp_path / "b")
    assert result["summary"]["verdict"] == "nothing applied"


def test_an_install_failure_and_the_time_budget(mini, agent_cfg, tmp_path, monkeypatch):
    from cleansweep.agents import environment

    plan = {"tool": "pip", "steps": [["false"]], "fallback": [], "source": "x"}
    monkeypatch.setattr(environment, "install_plan", lambda root: plan)
    agent_cfg["core"]["agents"]["install"] = "auto"
    result = ends_with_a_report(mini, agent_cfg, tmp_path / "a")
    report = (tmp_path / "a" / "out" / "CLEANUP_REPORT.md").read_text()
    assert "- Environment: failed (false: exit 1)" in report
    assert result["summary"]["verdict"] == "everything runs"  # with this interpreter
    agent_cfg["core"]["agents"]["install"] = "off"
    agent_cfg["core"]["agents"]["budget"] = {"minutes": 0.001}
    result = ends_with_a_report(mini, agent_cfg, tmp_path / "b")
    assert result["summary"]["stopped"] == "the run's time budget is used up"
