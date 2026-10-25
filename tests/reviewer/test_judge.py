import json
import re

import pytest

from cleansweep.core.models import CleanupItem, CodeUnit
from cleansweep.llm import FakeLLM
from cleansweep.reviewer import judge_items
from cleansweep.reviewer.judge import group_requests, signals


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


def sent_ids(llm):
    return [re.findall(r'"item_id": "(\w+)"', call[-1]["content"]) for call in llm.calls]


def test_keep_moves_item_to_suggest_with_reason(toy_repo):
    items = [make("a"), make("b"), make("c")]
    llm = judge_reply(("a", "remove"), ("b", "suggest"), ("c", "keep"))
    out = {i.item_id: i for i in judge_items(items, toy_repo, llm, mode="gatekeeper")}
    assert set(out) == {"a", "b", "c"}
    assert out["a"].lane == "safe" and out["a"].llm_confidence == 0.8
    assert out["b"].lane == "suggest" and out["b"].reason == "suggest because"
    assert out["c"].lane == "suggest" and out["c"].action == "report_only"
    assert out["c"].reason == "Judge thinks this is still used: keep because"
    assert "llm judge: keep (confidence 0.8)" in out["c"].evidence


def test_advisory_mode_keeps_detector_lanes(toy_repo):
    items = [
        make("a"),
        make("b"),
        make("c", lane="suggest"),
        make("s", category="security", lane="suggest"),
    ]
    llm = judge_reply(("a", "keep"), ("b", "suggest"), ("c", "remove"), ("s", "remove"))
    out = {i.item_id: i for i in judge_items(items, toy_repo, llm, mode="advisory")}
    assert [out[k].lane for k in "abcs"] == ["safe", "safe", "suggest", "suggest"]
    assert out["a"].action == "delete_unit"
    assert out["a"].reason.startswith("Judge thinks this is still used:")
    assert out["s"].action == "report_only" and out["s"].llm_confidence == 0.8


def test_same_file_items_share_a_request(toy_repo):
    items = [make("a1", "a.py"), make("b1", "b.py"), make("a2", "a.py"), make("a3", "a.py")]
    llm = judge_reply()
    judge_items(items, toy_repo, llm, batch_size=2)
    batches = [set(ids) for ids in sent_ids(llm)]
    assert {"a1", "a2", "a3"} in batches
    assert {"b1"} in batches


def test_duplicate_pairs_share_a_request():
    dup_a = make("d1", "discounts.py", "duplicate", keep_target="utils.py::round_price")
    dup_b = make("d2", "storage.py", "duplicate", keep_target="utils.py::round_price")
    keeper_file = make("u1", "utils.py")
    other = make("o1", "cart.py")
    requests = group_requests([dup_a, other, dup_b, keeper_file], batch_size=2)
    ids = [{i.item_id for i in r} for r in requests]
    assert {"d1", "d2", "u1"} in ids


def test_signals_reach_the_prompt(toy_repo):
    dep = CleanupItem(
        "dep",
        CodeUnit("requirements.txt", "dependency", "requests"),
        "unused_dependency",
        "remove_dependency",
        "safe",
        "r",
        ["deptry DEP002: unused", "requests is not mentioned in any config, CI or script file"],
    )
    dup = make("dup", category="duplicate", keep_target="shopcart/utils.py::round_price")
    dup.evidence = ["near-identical body to shopcart/utils.py::round_price (similarity 0.85)"]
    assert signals(dep) == {
        "deptry_code": "DEP002",
        "imported_anywhere_in_repo": False,
        "mentioned_in_config_or_ci": False,
    }
    assert signals(dup)["duplicate_similarity"] == 0.85
    assert signals(dup)["identical_body"] is False
    llm = judge_reply()
    judge_items([dep, make("v")], toy_repo, llm)
    prompt = llm.calls[0][-1]["content"]
    assert '"vulture_confidence": 60' in prompt
    assert "strong evidence for removal" in prompt


def test_leftover_files_get_import_and_main_signals(toy_repo):
    from cleansweep.analysis import build_graph

    graph = build_graph(toy_repo)
    debug = make("d", "debug_cart.py", "leftover_file")
    debug.unit = CodeUnit("debug_cart.py", "file")
    repro = make("r", "reproduce_bug.py", "leftover_file")
    repro.unit = CodeUnit("reproduce_bug.py", "file")
    sig = signals(debug, graph, toy_repo)
    assert "reachable_from_entry_points" not in sig
    assert sig["imported_by"] == 0
    assert sig["has_main_block"] is True
    assert sig["mentioned_in_config"] is False
    assert signals(repro, graph, toy_repo)["has_main_block"] is False
    llm = judge_reply()
    judge_items([debug], toy_repo, llm, graph=graph)
    prompt = llm.calls[0][-1]["content"]
    assert '"has_main_block": true' in prompt
    assert "typical leftover" in prompt


def test_unreadable_reply_keeps_items(toy_repo):
    class Broken(FakeLLM):
        def chat_json(self, messages, temperature=0.0, seed=None):
            raise ValueError("bad json")

    items = [make("a")]
    assert judge_items(items, toy_repo, Broken(), mode="gatekeeper")[0].lane == "safe"


def test_format_items_skip_the_judge(toy_repo):
    fmt = make("f", "shopcart/pricing.py", "format")
    fmt.action = "format"
    items = [fmt, make("a")]
    llm = judge_reply(("f", "keep"), ("a", "remove"))
    out = {i.item_id: i for i in judge_items(items, toy_repo, llm, mode="gatekeeper")}
    assert sent_ids(llm) == [["a"]]
    assert out["f"].lane == "safe" and out["f"].action == "format"
    assert out["f"].reason == "Formatting only; the Guard checks the code structure is unchanged."
    assert out["f"].llm_confidence is None


def test_only_format_items_means_no_request(toy_repo):
    fmt = make("f", "shopcart/pricing.py", "format")
    llm = judge_reply()
    judge_items([fmt], toy_repo, llm, mode="gatekeeper")
    assert llm.calls == []


def test_mode_from_env_overrides_config(monkeypatch, toy_repo):
    llm = judge_reply(("a", "keep"))
    monkeypatch.setenv("CLEANSWEEP_JUDGE_MODE", "off")
    assert judge_items([make("a")], toy_repo, llm)[0].lane == "safe"
    assert llm.calls == []
    monkeypatch.setenv("CLEANSWEEP_JUDGE_MODE", "Advisory")
    out = judge_items([make("a")], toy_repo, llm)[0]
    assert out.lane == "safe" and out.reason.startswith("Judge thinks this is still used:")
    assert judge_items([make("a")], toy_repo, llm, mode="gatekeeper")[0].lane == "suggest"
    monkeypatch.setenv("CLEANSWEEP_JUDGE_MODE", "sometimes")
    with pytest.raises(ValueError, match="CLEANSWEEP_JUDGE_MODE"):
        judge_items([make("a")], toy_repo, llm)


def test_no_llm_and_bad_mode(toy_repo):
    items = [make("a")]
    assert judge_items(items, toy_repo, None) == items
    with pytest.raises(ValueError):
        judge_items(items, toy_repo, FakeLLM(), mode="strict")
