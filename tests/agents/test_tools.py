from types import SimpleNamespace

from cleansweep.agents.knowledge import KnowledgeBase
from cleansweep.agents.lessons import LessonStore, matches, name_pattern, pattern_for
from cleansweep.agents.tools import investigation_tools
from cleansweep.analysis import build_graph
from cleansweep.core.models import CleanupItem, CodeUnit


def _rt(ws):
    return SimpleNamespace(
        ws=ws, graph=build_graph(ws.path), lessons=LessonStore(), kb=KnowledgeBase(), cache=None
    )


def test_investigation_tools_on_the_toy_repo(toy_ws):
    tools = investigation_tools(_rt(toy_ws))
    refs = tools.call("find_references", {"name": "format_money_v2"})
    assert "graph callers: none" in refs and "text matches in code: 0" in refs
    used = tools.call("find_references", {"name": "compute_total"})
    assert "in tests: 0" not in used or "text matches in code: 0" not in used
    assert "AST: DIFFERENT" in tools.call(
        "compare_functions",
        {"a": "shopcart/discounts.py::_round_price", "b": "shopcart/storage.py::_safe_round"},
    )
    assert "imports of requests: 0" in tools.call("check_dependency_usage", {"package": "requests"})
    assert "tests related to shopcart/cart.py" in tools.call(
        "find_related_tests", {"path": "shopcart/cart.py"}
    )
    assert tools.call(
        "read_code", {"path": "shopcart/utils.py", "start_line": 1, "end_line": 3}
    ).startswith("shopcart/utils.py lines 1-3")
    assert tools.call(
        "read_code", {"path": "../../etc/passwd", "start_line": 1, "end_line": 3}
    ).startswith("no file")
    assert tools.call("query_lessons", {"pattern": "anything"}) == "no lessons match"
    assert tools.call("no_such_tool", {}).startswith("error: KeyError")


def test_the_knowledge_base_answers_from_the_mined_tables():
    kb = KnowledgeBase()
    answer = kb.query("leftover_file", framework="textual")
    assert "rule:" in answer and "mined maintainer removal requests" in answer
    assert "textual calls these methods by name" in answer
    assert kb.prior("leftover_file") and kb.prior("leftover_file") < 1
    assert kb.query("unheard_of") == "nothing mined about unheard_of"


def _item(path, name, category="dead_code"):
    unit = CodeUnit(path, "function", name, 1, 2)
    return CleanupItem("x", unit, category, "delete_unit", "safe", "r")


def test_lesson_patterns_match_similar_items_only():
    assert name_pattern("on_mount") == "on_*" and name_pattern("_safe_round") == "_safe_*"
    assert name_pattern("helper") == "helper"
    pattern = pattern_for(_item("ui/screens.py", "Dash.on_mount"), framework="textual")
    assert matches(pattern, _item("ui/app.py", "App.on_click"), framework="textual")
    assert not matches(pattern, _item("core/app.py", "App.on_click"), framework="textual")
    assert not matches(pattern, _item("ui/app.py", "App.helper"), framework="textual")
    assert not matches(
        pattern, _item("ui/app.py", "App.on_click", "duplicate"), framework="textual"
    )
    store = LessonStore()
    lesson = store.add(pattern, "Textual calls on_* methods by name", {"package": "P1"})
    assert lesson["lesson_id"] == "L1" and store.search("on_click") == [lesson]
    assert store.matching(_item("ui/x.py", "W.on_key"), framework="textual") == [lesson]
