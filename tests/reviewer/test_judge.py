import json

from cleansweep.core.models import CleanupItem, CodeUnit
from cleansweep.llm import FakeLLM
from cleansweep.reviewer import judge_items


def make(item_id, path="shopcart/utils.py", category="dead_code", lane="safe", **extra):
    action = "report_only" if category == "security" else "delete_unit"
    return CleanupItem(
        item_id,
        CodeUnit(path, "function", "slugify", 22, 23),
        category,
        action,
        lane,
        "detector reason",
        ["vulture: unused function (60% confidence)"],
        ["vulture"],
        **extra,
    )


def judge_reply(*rows):
    return FakeLLM(
        {
            "cleanup plan": json.dumps(
                [
                    {"item_id": i, "decision": d, "reason": f"{d} because", "confidence": 0.8}
                    for i, d in rows
                ]
            )
        }
    )


def test_keep_moves_item_to_suggest_with_reason(toy_repo):
    items = [make("a"), make("b"), make("c")]
    llm = judge_reply(("a", "remove"), ("b", "suggest"), ("c", "keep"))
    out = {i.item_id: i for i in judge_items(items, toy_repo, llm)}
    assert set(out) == {"a", "b", "c"}
    assert out["a"].lane == "safe" and out["a"].llm_confidence == 0.8
    assert out["b"].lane == "suggest" and out["b"].reason == "suggest because"
    assert out["c"].lane == "suggest" and out["c"].action == "report_only"
    assert out["c"].reason == "Judge thinks this is still used: keep because"
    assert "llm judge: keep (confidence 0.8)" in out["c"].evidence


def test_unreadable_reply_keeps_items(toy_repo):
    class Broken(FakeLLM):
        def chat_json(self, messages, temperature=0.0, seed=None):
            raise ValueError("bad json")

    items = [make("a")]
    assert judge_items(items, toy_repo, Broken())[0].lane == "safe"


def test_no_llm(toy_repo):
    items = [make("a")]
    assert judge_items(items, toy_repo, None) == items
