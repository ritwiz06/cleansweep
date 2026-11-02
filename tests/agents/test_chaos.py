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
