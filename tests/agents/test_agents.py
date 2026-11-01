"""One focused test per agent, on a small runtime over a scratch copy of the mini project."""

import pytest

from cleansweep.agents import (
    auditor,
    engineer,
    explorer,
    fixer,
    investigator,
    manager,
    planner,
    reporter,
    tester,
    validator,
)
from cleansweep.agents.delivery import prepare_workspace
from cleansweep.agents.runtime import Package, Runtime
from cleansweep.agents.scripted import ScriptedLLM, final


@pytest.fixture
def rt(mini, agent_cfg, tmp_path):
    ws, _ = prepare_workspace(mini, tmp_path / "ws", agent_cfg["core"]["sandbox"])
    return Runtime(ws, agent_cfg, None, tmp_path / "out")


def _llm_rt(rt, llm):
    from cleansweep.agents.llm import AgentLLM

    rt.llm = AgentLLM(llm, rt.redact, rt.log, rt.run_budget)
    return rt


def _ready(rt):
    """Brief, baseline, candidates and verdicts, as the earlier phases leave them."""
    explorer.run(rt)
    tester.baseline(rt)
    auditor.run(rt)
    investigator.run(rt)
    return rt


def test_explorer_writes_the_brief_and_sends_it(rt):
    llm = ScriptedLLM(
        default=final({"summary": "A tiny shop library.", "notes": ["tests run with pytest"]})
    )
    explorer.run(_llm_rt(rt, llm))
    assert rt.brief["summary"] == "A tiny shop library." and rt.brief["test_command"] == "pytest"
    assert rt.brief["install_command"].startswith("none needed") and rt.brief["name"] == "mini"
    msg = rt.board.messages[-1]
    assert msg.type == "brief" and "tester" in msg.recipients and "engineer" not in msg.recipients


def test_tester_baseline_finds_flaky_tests_and_compare_sees_removed_ones(rt):
    from pathlib import Path

    flaky = Path(rt.ws.path) / "tests" / "test_flaky.py"
    flaky.write_text(
        "from pathlib import Path\n\n\ndef test_flips():\n"
        "    p = Path(__file__).with_suffix('.n')\n"
        "    n = int(p.read_text()) if p.exists() else 0\n"
        "    p.write_text(str(n + 1))\n    assert n % 2 == 0\n"
    )
    rt.ws.checkpoint("flaky test")
    tester.baseline(rt)
    assert rt.baseline["flaky"] == ["tests.test_flaky::test_flips"] and rt.baseline["passed"] == 2
    flaky.unlink()
    result, statuses = tester._run(rt)
    assert tester.compare(rt, result, statuses) == ([], [])  # flaky tests are not compared


def test_auditor_finds_candidates_with_priors(rt):
    auditor.run(rt)
    cats = sorted(i.category for i in rt.items.values())
    assert cats == ["dead_code", "dead_code", "unused_import", "wrapper"]
    dead = next(i for i in rt.items.values() if i.category == "dead_code")
    assert any(e.startswith("knowledge base:") for e in dead.evidence)
    assert rt.board.messages[-1].type == "candidates"


def test_investigator_rules_and_fixed_verdicts(rt):
    auditor.run(rt)
    investigator.run(rt)
    lanes = {i.unit.key: i.lane for i in rt.items.values()}
    assert (
        lanes["shop/core.py::legacy_alpha"] == "safe" and lanes["shop/core.py::total"] == "suggest"
    )
    assert all(v["evidence"] for v in rt.verdicts.values() if v["stop"] == "rules")
    assert sum(m.type == "verdict" for m in rt.board.messages) == len(rt.items)


def test_planner_packages_and_blueprint(rt):
    _ready(rt)
    planner.run(rt)
    assert [p.goal for p in rt.packages] == [
        "Remove 1 unused import in shop/core.py",
        "Remove 1 unused function or class in shop/core.py",
        "Remove 1 unused function or class in shop/extra.py",
    ]
    text = (rt.out / "blueprint.md").read_text()
    assert "## P1" in text and "Rollback:" in text and "## Suggestions (not applied)" in text


def test_engineer_applies_commits_and_reverts(rt):
    _ready(rt)
    planner.run(rt)
    for pkg in rt.packages:
        engineer.apply(rt, pkg)
        pkg.status = "kept"
        engineer.commit(rt, pkg)
    commits = [p.commit for p in rt.packages]
    assert len(set(commits)) == 3 and rt.delivery_tip == commits[-1]
    assert engineer.revert_last(rt) and rt.packages[-1].status == "reverted"
    assert rt.delivery_tip == rt.packages[1].commit  # the branch is rebuilt without it
    missing = Package("P9", "nothing", ["no-such-item"], [])
    rt.items["no-such-item"] = rt.items[rt.packages[0].items[0]]
    rt.ws.rollback(rt.ws.base)
    engineer.apply(rt, missing)  # the import is already gone at base? no: base still has it
    assert missing.status in ("applied", "skipped")


def test_validator_checks_the_ast_for_comment_only_packages(rt):
    from pathlib import Path

    core = Path(rt.ws.path) / "shop" / "core.py"
    core.write_text(core.read_text() + "\n# old = total([1])\n")
    rt.ws.checkpoint("commented code")
    auditor.run(rt)
    item = next(i for i in rt.items.values() if i.category == "commented_code")
    pkg = Package("P1", "g", [item.item_id], [item.unit.path])
    engineer.apply(rt, pkg)
    assert validator.check_package(rt, pkg) and pkg.verify["checks_result"]["ast_equal"] is True


def test_fixer_splits_repairs_and_rolls_back(rt):
    _ready(rt)
    planner.run(rt)
    pkg = rt.packages[1]
    pkg.items = pkg.items + rt.packages[2].items
    engineer.apply(rt, pkg)
    rt.current = 1
    pkg.failure = {"stage": "tests", "log": "boom"}
    assert fixer.run(rt, pkg) == "split" and rt.packages[2].package_id == "P2a"
    single = rt.packages[2]
    engineer.apply(rt, single)
    single.failure = {"stage": "probes", "log": "probes found a behavior change"}
    assert fixer.run(rt, single) == "rolled_back"  # no LLM: no repair turn
    assert rt.lessons.lessons and rt.board.messages[-2].type == "lesson"


def test_fixer_repair_turn_uses_its_prompt(rt):
    _ready(rt)
    planner.run(rt)
    pkg = rt.packages[0]
    engineer.apply(rt, pkg)
    patch = (
        "--- a/shop/extra.py\n+++ b/shop/extra.py\n@@ -1,5 +1,5 @@\n def used():\n"
        "-    return 1\n+    return 1  # kept\n \n \n def legacy_beta(y):\n"
    )
    llm = ScriptedLLM(default=f"```diff\n{patch}```")
    _llm_rt(rt, llm)
    pkg.failure = {"stage": "tests", "log": "tests/test_shop.py::test_used failed"}
    assert fixer.run(rt, pkg) == "retry" and pkg.turns == 1
    assert llm.calls[0][0]["role"] == "system" and "You are the Fixer" in llm.calls[0][0]["content"]


def test_reporter_writes_the_files_from_the_records(rt):
    _ready(rt)
    planner.run(rt)
    rt.final = {
        "ok": True,
        "passed": 2,
        "baseline_passed": 2,
        "new_failures": [],
        "tests_removed": [],
    }
    reporter.run(rt, {}, patches=False)
    report = (rt.out / "CLEANUP_REPORT.md").read_text()
    assert "**Result: everything runs.**" in report and "| Agent | Turns |" in report
    assert sorted(rt.files) == [
        "CHANGELOG_ENTRY.md",
        "CLEANUP_REPORT.md",
        "PR_DESCRIPTION.md",
        "blueprint.md",
    ]


def test_manager_routes_by_phase_and_stops_on_budget(rt):
    assert manager.decide(rt) == "explorer"
    assert rt.board.messages[-1].type == "task" and rt.board.messages[-1].recipients == ["explorer"]
    explorer.run(rt)
    assert manager.decide(rt) == "tester" and rt.phases.phase == "BASELINE"
    rt.run_budget.minutes = 1e-9  # out of time
    tester.baseline(rt)
    assert manager.decide(rt) == "reporter" and rt.phases.phase == "REPORT"
    assert rt.stopped == "the run's time budget is used up"


def test_a_policy_reason_survives_a_safe_verdict():
    from cleansweep.core.models import CleanupItem, CodeUnit

    item = CleanupItem(
        "i",
        CodeUnit("pkg/a.py", "function", "api"),
        "dead_code",
        "delete_unit",
        "suggest",
        "Public API of a published package: a person decides.",
    )
    investigator.apply_verdict(item, {"decision": "safe", "reason": "no callers", "evidence": []})
    assert item.lane == "suggest" and item.reason.startswith("Public API of a published package")
    assert "found no use either: no callers" in item.reason
