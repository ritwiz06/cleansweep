from cleansweep.agents import clean_project, validator
from cleansweep.agents.events import read_events
from cleansweep.agents.scripted import ScriptedLLM, final, tool


def _phases(out):
    return [
        e["payload"]["to"] for e in read_events(out / "events.jsonl") if e["kind"] == "phase_change"
    ]


def test_a_rollback_writes_a_lesson_that_changes_a_later_decision(
    mini, agent_cfg, tmp_path, monkeypatch
):
    real = validator.check_package

    def failing(rt, pkg):
        if any(rt.items[i].unit.name == "legacy_alpha" for i in pkg.applied):
            pkg.failure = {
                "stage": "probes",
                "log": "probes found a behavior change",
                "new_failures": [],
            }
            return False
        return real(rt, pkg)

    monkeypatch.setattr(validator, "check_package", failing)
    out = tmp_path / "out"
    result = clean_project(str(mini), agent_cfg, out=str(out), use_llm=False)
    report = result["report"]
    lessons = report.stats["agentic"]["lessons"]
    assert len(lessons) == 1 and lessons[0]["pattern"]["name_pattern"] == "legacy_*"
    status = {
        i.unit.key: r.status
        for i in report.plan.items
        for r in report.results
        if r.item_id == i.item_id
    }
    assert status["shop/core.py::legacy_alpha"] == "rolled_back"
    beta = next(i for i in report.plan.items if i.unit.key == "shop/extra.py::legacy_beta")
    assert (
        beta.lane == "suggest" and "lesson L1" in beta.reason and status[beta.unit.key] == "skipped"
    )
    assert _phases(out)[5:8] == ["EXECUTE", "PLAN", "EXECUTE"]  # the step back
    assert result["summary"]["verdict"] == "everything runs"


def test_a_worse_final_suite_reverts_packages(mini, agent_cfg, tmp_path, monkeypatch):
    from cleansweep.agents import tester

    real, calls = tester.final_check, []

    def final_check(rt):
        calls.append(1)
        ok = real(rt)
        if len(calls) == 1:  # pretend the first final run found a new failure
            rt.final.update(ok=False, new_failures=["tests/test_shop.py::test_total"])
            return False
        return ok

    monkeypatch.setattr(tester, "final_check", final_check)
    out = tmp_path / "out"
    result = clean_project(str(mini), agent_cfg, out=str(out), use_llm=False)
    packages = result["report"].stats["agentic"]["packages"]
    assert [p["status"] for p in packages].count("reverted") == 1
    assert _phases(out)[-5:] == ["FINAL_VERIFY", "EXECUTE", "FINAL_VERIFY", "REPORT", "DONE"]
    assert result["summary"]["verdict"] == "everything runs"
    log = result["report"].stats["agentic"]["branch"]
    assert log  # the branch was rebuilt without the reverted package


def test_an_exhausted_budget_sends_the_item_to_suggest(mini, agent_cfg, tmp_path):
    agent_cfg["core"]["agents"]["investigator"] = {"steps": 2, "llm_calls": 10, "seconds": 600}
    llm = ScriptedLLM(
        [("Candidate ", [tool("find_references", {"name": "legacy_alpha"})])],
        default=final({"summary": "A shop.", "notes": []}),
    )
    result = clean_project(str(mini), agent_cfg, out=str(tmp_path / "o"), llm=llm)
    agentic = result["report"].stats["agentic"]
    assert agentic["budget_exhausted"] == len(result["report"].plan.items) == 4
    assert agentic["decisions"]["safe"] == 0
    assert all(i.lane == "suggest" for i in result["report"].plan.items)
    assert all("budget ran out" in i.reason for i in result["report"].plan.items)
    assert result["summary"]["verdict"] == "nothing applied"


def test_the_investigator_must_cite_a_tool_result_and_the_lessons(mini, agent_cfg, tmp_path):
    llm = ScriptedLLM(
        [
            (
                "legacy_alpha",
                [
                    final({"decision": "safe", "reason": "obvious", "evidence": []}),
                    final({"decision": "safe", "reason": "obvious", "evidence": []}),
                ],
            ),
            (
                "legacy_beta",
                [
                    tool("find_references", {"name": "legacy_beta"}),
                    final(
                        {
                            "decision": "safe",
                            "reason": "no references",
                            "evidence": [{"result": "R1", "says": "none"}],
                        }
                    ),
                ],
            ),
            (
                "::os",
                [
                    tool("find_references", {"name": "os"}),
                    final(
                        {
                            "decision": "drop",
                            "reason": "keep it",
                            "evidence": [{"result": "R1", "says": "x"}],
                        }
                    ),
                ],
            ),
        ],
        default=final({"summary": "A shop.", "notes": []}),
    )
    result = clean_project(str(mini), agent_cfg, out=str(tmp_path / "o"), llm=llm)
    items = {i.unit.key: i for i in result["report"].plan.items}
    assert (
        items["shop/core.py::legacy_alpha"].lane == "suggest"
    )  # safe without evidence: rejected twice
    assert "answer stayed invalid" in items["shop/core.py::legacy_alpha"].reason
    assert items["shop/extra.py::legacy_beta"].lane == "safe"
    assert items["shop/core.py::os"].action == "report_only"  # dropped: reported, not applied
    assert any(
        "evidence cites" in m[-1]["content"] or "needs evidence" in m[-1]["content"]
        for m in llm.calls
    )


def test_a_planted_secret_never_reaches_the_llm(mini, agent_cfg, tmp_path):
    key = "AKIA" + "QWERTYUIOPASDFGH"
    (mini / "shop" / "settings.py").write_text(
        f'AWS_KEY = "{key}"\n\n\ndef legacy_gamma():\n    return AWS_KEY\n'
    )
    (mini / ".env").write_text("SETTING=" + "not-for-the-llm" + "\n")
    llm = ScriptedLLM(
        [
            (
                "legacy_gamma",
                [
                    tool("read_code", {"path": "shop/settings.py", "start_line": 1, "end_line": 5}),
                    tool("read_code", {"path": ".env", "start_line": 1, "end_line": 2}),
                    final(
                        {
                            "decision": "suggest",
                            "reason": "holds a key",
                            "evidence": [{"result": "R1"}],
                        }
                    ),
                ],
            )
        ],
        default=final({"summary": "A shop.", "notes": []}),
    )
    out = tmp_path / "o"
    clean_project(str(mini), agent_cfg, out=str(out), llm=llm)
    sent = "\n".join(m["content"] for call in llm.calls for m in call)
    assert "legacy_gamma" in sent and "[REDACTED" in sent
    assert key not in sent and "not-for-the-llm" not in sent and "[withheld" in sent
    assert key not in (out / "events.jsonl").read_text()
    assert all(key not in p.read_text() for p in (out / "cache").iterdir())
