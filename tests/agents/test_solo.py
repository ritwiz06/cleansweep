"""The single_agent ablation: one agent with every tool, scripted."""

import json

from cleansweep.agents import clean_project
from cleansweep.agents.scripted import ScriptedLLM, final, tool
from cleansweep.reviewer.detectors import item_id


def test_one_agent_applies_checks_keeps_and_reverts(mini, agent_cfg, tmp_path):
    agent_cfg["core"]["agents"]["ablation"] = "single_agent"
    unused = item_id("shop/core.py::os", "unused_import")
    dead = item_id("shop/core.py::legacy_alpha", "dead_code")
    script = [
        tool("find_candidates", {}),
        tool("apply_edit", {"item_id": unused}),
        tool("run_tests", {}),
        tool("keep", {"item_ids": [unused]}),
        tool("apply_edit", {"item_id": dead}),
        tool("revert", {"item_id": dead}),
        final({"summary": "removed one unused import"}),
    ]
    llm = ScriptedLLM([("You clean up a Python project on your own", script)])
    result = clean_project(str(mini), agent_cfg, out=str(tmp_path / "out"), llm=llm)
    report = result["report"]
    status = {r.item_id: r.status for r in report.results}
    assert status[unused] == "kept" and status[dead] == "rolled_back"
    agentic = report.stats["agentic"]
    assert agentic["verdict"] == "everything runs" and agentic["ablation"] == "single_agent"
    assert agentic["phases"] == ["ONBOARD", "BASELINE", "REPORT", "DONE"]
    assert set(agentic["agents"]) == {"solo"}
    assert (
        "-import os" in report.stats["final_diff"]
        and "legacy_alpha" not in report.stats["final_diff"]
    )
    events = [
        json.loads(line) for line in (tmp_path / "out" / "events.jsonl").read_text().splitlines()
    ]
    assert {e["agent"] for e in events if e["kind"] == "tool_call"} == {"solo", "tester"}


def test_without_an_llm_nothing_is_applied(mini, agent_cfg, tmp_path):
    agent_cfg["core"]["agents"]["ablation"] = "single_agent"
    result = clean_project(str(mini), agent_cfg, out=str(tmp_path / "out"), use_llm=False)
    assert result["report"].stats["agentic"]["verdict"] == "nothing applied"
    assert result["report"].stats["agentic"]["stopped"] == "no LLM"
