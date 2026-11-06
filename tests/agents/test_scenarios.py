"""The Manager's decision scenarios (tests/fixtures/scenarios), with scripted Manager replies."""

import importlib.util
import json
from pathlib import Path

import pytest

from cleansweep.agents import clean_project
from cleansweep.agents.scripted import ScriptedLLM

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "experiments" / "v2" / "exp_manager_scenarios.py"


def _script():
    spec = importlib.util.spec_from_file_location("exp_manager_scenarios", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _says(where: str, choice: str) -> ScriptedLLM:
    pick = json.dumps({"choice": choice, "reason": "scripted"})
    go_on = json.dumps({"choice": "continue", "reason": "scripted"})
    return ScriptedLLM([(where, pick), ("The rules propose", go_on)])


def _run(scenario, agent_cfg, tmp_path, manager_llm=None):
    script = _script()
    agents = agent_cfg["core"]["agents"]
    agents.update(script.SCENARIOS[scenario]["agents"], baseline_runs=3, **script.V2_CLEAN)
    out = tmp_path / scenario
    clean_project(
        str(script.FIXTURES / scenario),
        agent_cfg,
        out=str(out),
        use_llm=False,
        manager_llm=manager_llm,
    )
    report = json.loads((out / "report.json").read_text())
    return script.judge(scenario, report, script.events(out)), report


@pytest.mark.parametrize(
    ("scenario", "where", "choice", "right"),
    [
        ("rollbacks", "was rolled back", "replan", True),
        ("rollbacks", None, None, False),
        ("conflict", "final suite is worse", "continue", True),
        ("conflict", "final suite is worse", "revert_all", False),
        ("budget", "test-run budget is used", "stop", True),
        ("budget", None, None, False),
        ("no_baseline", None, None, True),
    ],
)
def test_scenarios_judge_the_managers_choice(scenario, where, choice, right, agent_cfg, tmp_path):
    llm = _says(where, choice) if where else None
    (got, did), report = _run(scenario, agent_cfg, tmp_path, llm)
    assert got is right, did
    verdict = report["stats"]["agentic"]["verdict"]
    assert verdict in ("everything runs", "nothing applied")  # never worse than the baseline
    if scenario == "budget":
        assert report["stats"]["test_runs"] == (9 if right else 10)
