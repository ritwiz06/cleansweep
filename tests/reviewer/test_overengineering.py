import json

import pandas as pd

from cleansweep.analysis import build_graph
from cleansweep.llm import FakeLLM
from cleansweep.reviewer import build_plan, run_detectors
from cleansweep.reviewer import overengineering as oe

KEY = "Look for over-engineering"


def write(tmp_path, files: dict[str, str]) -> str:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return str(tmp_path)


def test_select_files_prefers_agent_written(tmp_path):
    repo = write(
        tmp_path,
        {
            "a.py": "x = 1\n",
            "b.py": "y = 2\n",
            "scratch.py": "z = 3\n",
            "tests/test_a.py": "def test_a():\n    pass\n",
        },
    )
    assert oe.select_files(repo, None, {"scratch.py"}, 20) == ["a.py", "b.py"]
    assert oe.select_files(repo, None, set(), 1) == ["a.py"]
    features = pd.DataFrame({"written_by_agent": [1, -1]}, index=["b.py::f", "a.py::g"])
    assert oe.select_files(repo, features, set(), 20) == ["b.py"]


def test_pack_groups_small_files_under_the_budget():
    files = [("a.py", "x" * 40), ("b.py", "y" * 40), ("c.py", "z" * 40), ("big.py", "w" * 500)]
    requests = oe.pack(files, budget=100)
    assert [[p for p, _ in r] for r in requests] == [["a.py", "b.py"], ["c.py"], ["big.py"]]
    assert requests[-1][0][1].endswith("(rest of the file not shown)")


def findings_for_toy(toy_repo):
    graph = build_graph(toy_repo)
    add = graph.unit("shopcart/cart.py::Cart.add")
    v2 = graph.unit("shopcart/utils.py::format_money_v2")
    return graph, [
        {
            "path": "shopcart/cart.py",
            "start_line": add.start_line + 1,
            "end_line": add.start_line + 2,
            "kind": "extra_check",
            "reason": "Callers never pass a zero quantity.",
            "confidence": 0.6,
        },
        {
            "path": "shopcart/cart.py",
            "start_line": add.start_line,
            "end_line": add.start_line,
            "kind": "unused_parameter",
            "reason": "One parameter is never read.",
        },
        {
            "path": "shopcart/utils.py",
            "start_line": v2.start_line,
            "end_line": v2.end_line,
            "kind": "needless_abstraction",
            "reason": "Already a dead-code item.",
        },
        {"path": "nope.py", "start_line": 1, "end_line": 2, "kind": "extra_check", "reason": "x"},
        {
            "path": "shopcart/cart.py",
            "start_line": 900,
            "end_line": 901,
            "kind": "extra_check",
            "reason": "Out of range.",
        },
    ]


def test_findings_become_report_only_items(toy_repo):
    graph, findings = findings_for_toy(toy_repo)
    items = run_detectors(toy_repo, graph)
    llm = FakeLLM({KEY: json.dumps(findings)})
    new = oe.review_overengineering(items, toy_repo, graph, llm)
    assert len(new) == 1  # dead-code unit attached, bad path and bad lines dropped, two merged
    item = new[0]
    assert item.unit.key == "shopcart/cart.py::Cart.add"
    assert (item.category, item.action, item.lane) == ("other", "report_only", "suggest")
    assert item.unit.start_line == graph.unit("shopcart/cart.py::Cart.add").start_line
    assert item.evidence[0] == "over-engineering review"
    assert "Callers never pass a zero quantity." in item.reason
    assert item.llm_confidence == 0.6
    prompt = llm.calls[0][-1]["content"]
    assert "### shopcart/cart.py" in prompt and "reproduce_bug.py" not in prompt


def test_switches_turn_the_review_off(toy_repo, monkeypatch):
    graph, findings = findings_for_toy(toy_repo)
    llm = FakeLLM({KEY: json.dumps(findings)})
    monkeypatch.setenv("CLEANSWEEP_OVERENGINEERING", "0")
    assert oe.review_overengineering([], toy_repo, graph, llm) == []
    monkeypatch.delenv("CLEANSWEEP_OVERENGINEERING")
    monkeypatch.setattr(oe, "_settings", lambda: {"overengineering": False})
    assert oe.review_overengineering([], toy_repo, graph, llm) == []
    assert llm.calls == []
    assert oe.review_overengineering([], toy_repo, graph, None) == []


def test_build_plan_adds_over_engineering_items(toy_repo, monkeypatch):
    monkeypatch.setenv("CLEANSWEEP_JUDGE_MODE", "off")
    graph, findings = findings_for_toy(toy_repo)
    plan = build_plan(toy_repo, graph, FakeLLM({KEY: json.dumps(findings)}), use_llm=True)
    other = [i for i in plan.items if i.category == "other"]
    assert [i.unit.key for i in other] == ["shopcart/cart.py::Cart.add"]
    safe_positions = [n for n, i in enumerate(plan.items) if i.lane == "safe"]
    assert plan.items.index(other[0]) > max(safe_positions)


def round_price_lines(graph):
    start = graph.unit("shopcart/utils.py::round_price").start_line
    return start + 2, start + 3  # "if value is None:" and "return 0.0"


def test_tested_impossible_findings_are_dropped(toy_ws, caplog):
    graph = build_graph(toy_ws.path)
    coverage = oe.load_coverage(toy_ws.coverage_json())
    check, body = round_price_lines(graph)
    add = graph.unit("shopcart/cart.py::Cart.add")
    findings = [
        {
            "path": "shopcart/utils.py",
            "start_line": check,
            "end_line": body,
            "kind": "impossible_case",
            "reason": "The None check can never trigger.",
        },
        {
            "path": "shopcart/cart.py",
            "start_line": add.start_line + 1,
            "end_line": add.start_line + 2,
            "kind": "extra_check",
            "reason": "Callers never pass zero.",
        },
        {
            "path": "shopcart/cart.py",
            "start_line": add.start_line + 1,
            "end_line": add.start_line + 2,
            "kind": "needless_abstraction",
            "reason": "This branch is unreachable.",
        },
    ]
    with caplog.at_level("INFO", logger="cleansweep"):
        kept = oe.drop_tested(findings, coverage, toy_ws.path)
    assert [f["kind"] for f in kept] == ["extra_check"]
    assert f"dropped over-engineering finding shopcart/utils.py:{check}-{body}" in caplog.text
    assert "test_pricing.test_round_price" in caplog.text


def test_untested_or_uncovered_findings_are_kept():
    finding = {
        "path": "m.py",
        "start_line": 3,
        "end_line": 4,
        "kind": "impossible_case",
        "reason": "x",
    }
    assert oe.drop_tested([finding], {"m.py": {3: [], 9: ["t.test_a"]}}) == [finding]
    assert oe.drop_tested([finding], {}) == [finding]


def test_prompt_shows_test_calls(toy_repo):
    llm = FakeLLM({KEY: "[]"})
    oe.review_overengineering([], toy_repo, build_graph(toy_repo), llm)
    prompt = "\n".join(call[-1]["content"] for call in llm.calls)
    assert "Test calls:" in prompt
    assert "round_price: tests/test_pricing.py:" in prompt and "round_price(None)" in prompt


def test_calls_from_tests_keeps_three_per_function():
    lines = [("tests/t.py", n, f"assert f({n}) == {n}") for n in range(1, 6)]
    calls = oe.calls_from_tests("def f(x):\n    return x\n\n\ndef g():\n    pass\n", lines)
    assert len(calls) == 3 and all(c.startswith("  f: tests/t.py:") for c in calls)


def test_build_plan_runs_coverage_once_and_drops_tested_claims(toy_ws, monkeypatch):
    monkeypatch.setenv("CLEANSWEEP_JUDGE_MODE", "off")
    graph = build_graph(toy_ws.path)
    check, body = round_price_lines(graph)
    finding = {
        "path": "shopcart/utils.py",
        "start_line": check,
        "end_line": body,
        "kind": "impossible_case",
        "reason": "The None check can never trigger.",
    }
    plan = build_plan(toy_ws, graph, FakeLLM({KEY: json.dumps([finding])}), use_llm=True)
    assert toy_ws.test_runs == 1
    assert not [i for i in plan.items if i.category == "other"]


def test_a_failed_request_is_logged_and_skipped(toy_repo, caplog):
    class Down(FakeLLM):
        def chat_json(self, messages, temperature=0.0, seed=None):
            raise RuntimeError("524 gateway timeout")

    with caplog.at_level("WARNING", logger="cleansweep"):
        assert oe.review_overengineering([], toy_repo, build_graph(toy_repo), Down()) == []
    assert "over-engineering review skipped" in caplog.text and "524" in caplog.text


def none_check(graph, key):
    start = graph.unit(key).start_line
    path = key.split("::")[0]
    return {
        "path": path,
        "start_line": start + 2,
        "end_line": start + 3,
        "kind": "impossible_case",
        "reason": "value is never None.",
    }


def test_condition_covered_but_body_not_keeps_the_finding(toy_ws, caplog):
    graph = build_graph(toy_ws.path)
    coverage = oe.load_coverage(toy_ws.coverage_json())
    finding = none_check(graph, "shopcart/storage.py::_safe_round")
    lines = coverage["shopcart/storage.py"]
    assert lines.get(finding["start_line"]) and not lines.get(finding["end_line"])
    with caplog.at_level("INFO", logger="cleansweep"):
        assert oe.drop_tested([finding], coverage, toy_ws.path) == [finding]
    assert "tests run the condition but not the guarded code" in caplog.text


def test_body_covered_drops_the_finding(toy_ws):
    graph = build_graph(toy_ws.path)
    coverage = oe.load_coverage(toy_ws.coverage_json())
    finding = none_check(graph, "shopcart/utils.py::round_price")
    assert oe.drop_tested([finding], coverage, toy_ws.path) == []
    one_line = {**finding, "end_line": finding["start_line"]}
    safe_round = none_check(graph, "shopcart/storage.py::_safe_round")
    single = {**safe_round, "end_line": safe_round["start_line"]}  # only the covered condition
    assert oe.drop_tested([one_line, single], coverage, toy_ws.path) == []


def test_try_except_and_assert_guards(tmp_path):
    (tmp_path / "m.py").write_text(
        "def f(x):\n"
        "    try:\n"
        "        return int(x)\n"
        "    except ValueError:\n"
        "        return 0\n"
        "    assert x\n"
        "    return 1\n"
    )
    source = (tmp_path / "m.py").read_text()
    assert oe.evidence_lines(source, 2, 5) == {5}
    assert oe.evidence_lines(source, 6, 7) == set()
    caught = {
        "path": "m.py",
        "start_line": 2,
        "end_line": 5,
        "kind": "impossible_case",
        "reason": "x is always a valid number.",
    }
    asserted = {**caught, "start_line": 6, "end_line": 7}
    try_only = {"m.py": {2: ["t.test_a"], 3: ["t.test_a"]}}
    with_except = {"m.py": {2: ["t.test_a"], 4: ["t.test_b"], 5: ["t.test_b"]}}
    assert oe.drop_tested([caught], try_only, str(tmp_path)) == [caught]
    assert oe.drop_tested([caught], with_except, str(tmp_path)) == []
    assert oe.drop_tested(
        [asserted], {"m.py": {6: ["t.test_a"], 7: ["t.test_a"]}}, str(tmp_path)
    ) == [asserted]


def test_finding_on_an_existing_item_is_attached(toy_repo, caplog):
    graph = build_graph(toy_repo)
    items = run_detectors(toy_repo, graph)
    dup = next(i for i in items if i.unit.key == "shopcart/storage.py::_safe_round")
    lane, action, evidence = dup.lane, dup.action, list(dup.evidence)
    start = graph.unit("shopcart/storage.py::_safe_round").start_line
    add = graph.unit("shopcart/cart.py::Cart.add")
    findings = [
        {
            "path": "shopcart/storage.py",
            "start_line": start + 2,
            "end_line": start + 3,
            "kind": "impossible_case",
            "reason": "value is never None here.",
        },
        {
            "path": "shopcart/cart.py",
            "start_line": add.start_line + 1,
            "end_line": add.start_line + 2,
            "kind": "extra_check",
            "reason": "Callers never pass 0.",
        },
    ]
    with caplog.at_level("INFO", logger="cleansweep"):
        new = oe.review_overengineering(
            items, toy_repo, graph, FakeLLM({KEY: json.dumps(findings)})
        )
    assert [i.unit.key for i in new] == ["shopcart/cart.py::Cart.add"]
    assert (dup.lane, dup.action) == (lane, action)
    assert dup.evidence == [*evidence, "over-engineering review: value is never None here."]
    assert "overengineering" in dup.sources
    assert "attached over-engineering finding shopcart/storage.py" in caplog.text
