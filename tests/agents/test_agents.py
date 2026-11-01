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


CART_SCREEN = (
    "from textual.screen import Screen\nfrom textual.widgets import Label\n\n\n"
    "class CartScreen(Screen):\n    def compose(self):\n        yield Label('Your cart')\n"
)


def test_validator_ui_check_fails_a_package_that_changes_a_screen(mini, agent_cfg, tmp_path):
    pytest.importorskip("textual")
    from pathlib import Path

    (mini / "shop" / "ui.py").write_text(CART_SCREEN)
    ws, _ = prepare_workspace(mini, tmp_path / "ws", agent_cfg["core"]["sandbox"])
    rt = Runtime(ws, agent_cfg, None, tmp_path / "out")
    explorer.run(rt)
    tester.baseline(rt)
    assert rt.brief["ui_framework"] == "textual"
    assert manager.decide(rt) == "validator"  # the UI baseline comes before AUDIT
    validator.ui_baseline(rt)
    msg = rt.board.messages[-1]
    assert msg.type == "ui_baseline" and msg.body["classes"] == 1 and "manager" in msg.recipients
    pkg = Package("P1", "g", [], ["shop/ui.py"])
    record, log = validator._ui(rt, pkg, [])
    assert record["ok"] and record["classes"] == 1 and log is None
    ui = Path(ws.path) / "shop" / "ui.py"
    ui.write_text(ui.read_text().replace("Your cart", "Your basket"))
    record, log = validator._ui(rt, pkg, [])
    assert not record["ok"] and record["changed"] == ["shop.ui.CartScreen"]
    assert log.startswith("the UI check found a difference")


def test_validator_ui_check_is_not_applicable_without_textual(rt):
    pkg = Package("P1", "g", [], [])
    rt.brief = {"ui_framework": None}
    assert validator._ui(rt, pkg, []) == (
        "not applicable: the project has no UI framework",
        None,
    )
    rt.brief = {"ui_framework": "streamlit"}
    record, log = validator._ui(rt, pkg, [])
    assert record.startswith("not applicable: the project's UI uses streamlit") and log is None


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


def test_explorer_finds_the_formatter_a_project_enforces(tmp_path):
    from cleansweep.agents.explorer import enforced_formatter

    assert enforced_formatter(tmp_path) is None
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("steps:\n  - run: ruff check .\n  - run: pytest\n")
    assert enforced_formatter(tmp_path) is None  # linting is not formatting
    workflow.write_text("steps:\n  - run: black --check .\n")
    assert enforced_formatter(tmp_path) == "black (.github/workflows/ci.yml)"
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
        "    hooks:\n      - id: ruff\n      - id: ruff-format\n"
    )
    assert enforced_formatter(tmp_path) == "ruff format (.pre-commit-config.yaml)"


def test_formatting_is_safe_only_where_a_formatter_is_enforced():
    from cleansweep.core.models import CleanupItem, CodeUnit

    cases = [
        ({"formatter": None}, "enforced", "suggest"),
        ({"formatter": "black (.pre-commit-config.yaml)"}, "enforced", "safe"),
        ({"formatter": None}, "always", "safe"),
    ]
    for brief, policy, lane in cases:
        item = CleanupItem("f", CodeUnit("pkg/a.py", "file"), "format", "format", "safe", "x")
        investigator.apply_verdict(item, investigator._fixed(item, brief, policy))
        assert item.lane == lane, (brief, policy)
        if lane == "suggest":
            assert item.reason.startswith("The project doesn't enforce a formatter")


def test_a_project_without_a_formatter_gets_formatting_as_a_suggestion(rt):
    from pathlib import Path

    (Path(rt.ws.path) / "shop" / "messy.py").write_text("def f( x ):\n    return x*2\n")
    rt.ws.checkpoint("an unformatted file")
    _ready(rt)
    fmt = [i for i in rt.items.values() if i.category == "format"]
    assert fmt and all(i.lane == "suggest" for i in fmt) and rt.brief["formatter"] is None


def _manager_says(choice: str, reason: str = "because") -> ScriptedLLM:
    import json

    return ScriptedLLM([("The rules propose", json.dumps({"choice": choice, "reason": reason}))])


def _decisions(rt) -> list[dict]:
    return [
        e["payload"]
        for e in rt.log.events
        if e["kind"] == "decision" and e["payload"].get("rule") == "llm_manager"
    ]


def test_llm_manager_goes_on_and_logs_its_reason(rt):
    manager.decide(rt)
    explorer.run(rt)  # offline: the brief from the facts
    llm = _manager_says("continue", "the brief is complete")
    assert manager.decide(_llm_rt(rt, llm)) == "tester" and rt.phases.phase == "BASELINE"
    (logged,) = _decisions(rt)
    assert logged["choice"] == "continue" and logged["text"] == "the brief is complete"
    assert logged["proposed"] == "BASELINE" and logged["options"] == ["continue", "stop"]


def test_llm_manager_can_stop_but_a_bad_choice_leaves_it_to_the_rules(rt):
    manager.decide(rt)
    explorer.run(rt)
    llm = _manager_says("jump", "skip ahead")
    assert manager.decide(_llm_rt(rt, llm)) == "tester"  # not an option: the rules decide
    assert "not an option" in _decisions(rt)[-1]["text"]
    tester.baseline(rt)
    rt.llm = None
    _llm_rt(rt, _manager_says("stop", "the tests barely run"))
    assert manager.decide(rt) == "reporter" and rt.stopped == "the Manager chose to stop"


def test_llm_manager_sends_undecided_candidates_back_at_most_twice(rt):
    _ready(rt)
    for phase in ("BASELINE", "AUDIT", "INVESTIGATE"):
        rt.phases.go(phase, "test")
    item = next(i for i in rt.items.values() if i.unit.name == "legacy_alpha")
    rt.verdicts[item.item_id]["stop"] = "budget"  # the Investigator could not decide it
    item.lane = "suggest"
    _llm_rt(rt, _manager_says("go_back:INVESTIGATE", "two steps more may settle it"))
    assert manager.decide(rt) == "investigator" and rt.phases.phase == "INVESTIGATE"
    assert rt.retry == {item.item_id} and item.item_id not in rt.verdicts
    assert item.lane == "safe"  # back to the detector's lane for the new look
    rt.llm_back_steps = manager.LLM_STEP_BACKS
    rt.verdicts[item.item_id] = {"decision": "suggest", "stop": "budget"}
    assert "go_back:INVESTIGATE" not in manager._choices(rt, "PLAN")


def test_rule_based_manager_never_asks_the_llm(rt):
    rt.manager_mode = "rules"
    manager.decide(rt)
    explorer.run(rt)
    llm = _manager_says("stop")
    assert manager.decide(_llm_rt(rt, llm)) == "tester" and llm.calls == [] and not _decisions(rt)


def _near_duplicate():
    from cleansweep.core.models import CleanupItem, CodeUnit

    return CleanupItem(
        "d",
        CodeUnit("shop/a.py", "function", "fmt"),
        "duplicate",
        "report_only",
        "suggest",
        "Near-duplicate of shop/b.py::fmt.",
        keep_target="shop/b.py::fmt",
    )


def test_thorough_mode_takes_the_investigators_word_on_rewrites_only():
    safe = {"decision": "safe", "reason": "same body", "evidence": []}
    item = _near_duplicate()
    investigator.apply_verdict(item, dict(safe))
    assert item.lane == "suggest" and item.action == "report_only"  # safe mode: detector lane
    item = _near_duplicate()
    investigator.apply_verdict(item, dict(safe), "thorough")
    assert item.lane == "safe" and item.action == "replace_with" and "thorough" in item.sources
    assert "only if the probes run cases on it" in item.reason
    dead = _near_duplicate()
    dead.category = "dead_code"
    investigator.apply_verdict(dead, dict(safe), "thorough")
    assert dead.lane == "suggest"


def test_thorough_rewrite_comes_from_exact_edits_in_one_file(rt):
    import json
    from pathlib import Path

    from cleansweep.agents import engineer
    from cleansweep.analysis import build_graph

    root = Path(rt.ws.path)
    body = "def fmt(x):\n    return f'{x:.2f}'\n"
    (root / "shop" / "b.py").write_text(body)
    (root / "shop" / "a.py").write_text(body + "\n\ndef show(x):\n    return fmt(x)\n")
    rt.graph = build_graph(rt.ws.path)
    item = _near_duplicate()
    item.evidence = ["same normalized body"]
    edits = [{"old": body, "new": "from shop.b import fmt\n"}]
    good = ScriptedLLM([("Remove the duplicate `fmt`", json.dumps({"edits": edits}))])
    patch = engineer.llm_rewrite(_llm_rt(rt, good), item, rt.budget("engineer"))
    assert "+from shop.b import fmt" in patch and "-def fmt(x):" in patch
    assert rt.ws.apply_patch(patch) and "fmt(x)" in (root / "shop" / "a.py").read_text()
    rt.llm = None
    missing = [{"old": "def nowhere():", "new": ""}]
    bad = ScriptedLLM([("Remove the duplicate `fmt`", json.dumps({"edits": missing}))])
    assert engineer.llm_rewrite(_llm_rt(rt, bad), item, rt.budget("engineer")) == ""
