import json

from cleansweep.core.models import CleanupItem, CodeUnit
from cleansweep.llm import FakeLLM
from cleansweep.reviewer import judge_items


def make(i):
    return CleanupItem(
        i,
        CodeUnit("shopcart/utils.py", "function", "slugify", 22, 23),
        "dead_code",
        "delete_unit",
        "safe",
        "old",
        ["e"],
    )


def test_decisions_map_to_lanes(toy_repo):
    reply = json.dumps(
        [
            {"item_id": "a", "decision": "remove", "reason": "Never used.", "confidence": 0.9},
            {
                "item_id": "b",
                "decision": "suggest",
                "reason": "Might be a plugin.",
                "confidence": 0.5,
            },
            {"item_id": "c", "decision": "keep", "reason": "Used by the CLI.", "confidence": 0.8},
        ]
    )
    llm = FakeLLM({"cleanup plan": reply})
    out = {i.item_id: i for i in judge_items([make("a"), make("b"), make("c")], toy_repo, llm)}
    assert set(out) == {"a", "b"}
    assert out["a"].lane == "safe" and out["a"].llm_confidence == 0.9
    assert out["b"].lane == "suggest" and out["b"].reason == "Might be a plugin."


def test_no_llm_leaves_items_alone(toy_repo):
    items = [make("a")]
    assert judge_items(items, toy_repo, None) == items
