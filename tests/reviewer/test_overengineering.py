import json

import pandas as pd

from cleansweep.analysis import build_graph
from cleansweep.llm import FakeLLM
from cleansweep.reviewer import overengineering as oe
from cleansweep.reviewer import run_detectors

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
    assert len(new) == 1  # dead-code unit skipped, bad path and bad lines dropped, two merged
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

