"""Investigation batching on a scratch copy of the mini project, with a fake LLM that answers
every candidate it is asked about."""

import json
import re
import threading

import pytest

from cleansweep.agents import investigator
from cleansweep.agents.batching import batch_on
from cleansweep.agents.delivery import prepare_workspace
from cleansweep.agents.llm import AgentLLM
from cleansweep.agents.runtime import Runtime
from cleansweep.core.models import CodeUnit
from cleansweep.reviewer.detectors import make_item

BATCH = "give one verdict for each"


class PerCandidate:
    """Answers a batch with one verdict per candidate in it and a single investigation with
    one verdict; decide(name) picks each decision, and each verdict cites the candidate's
    first result. batch_reply, when set, replaces every batch answer."""

    model = "fake"

    def __init__(self, decide=lambda name: "suggest", batch_reply: str | None = None):
        self.decide, self.batch_reply = decide, batch_reply
        self.tasks: list[str] = []
        self._lock = threading.Lock()

    def chat(self, messages, temperature=0.0, seed=None, extra_body=None) -> str:
        task = messages[1]["content"]
        with self._lock:
            self.tasks.append(task)
        verdicts = []
        for block in task.split("Candidate ")[1:]:
            name = re.search(r"unit: \S+::(\S+)", block).group(1)
            first = re.search(r"\n(R\d+) ", block).group(1)
            verdicts.append(
                {
                    "item_id": block.split("\n", 1)[0].strip(),
                    "decision": self.decide(name),
                    "reason": f"looked at {name}",
                    "evidence": [{"result": first, "says": "the first check"}],
                }
            )
        if BATCH in task:
            return self.batch_reply or json.dumps({"final": {"verdicts": verdicts}})
        return json.dumps({"final": verdicts[0]})

    def usage(self) -> dict:
        return {"llm_calls": len(self.tasks)}


@pytest.fixture
def rt(mini, agent_cfg, tmp_path):
    ws, _ = prepare_workspace(mini, tmp_path / "ws", agent_cfg["core"]["sandbox"])
    rt = Runtime(ws, agent_cfg, None, tmp_path / "out")
    rt.acfg["investigate_batch"] = "on"
    return rt


def _item(name: str, category: str = "dead_code"):
    action = "delete_unit" if category == "dead_code" else "replace_with"
    unit = CodeUnit("shop/core.py", "function", name, 1, 2)
    return make_item(unit, category, action, "safe", "r", ["e"], ["test"])


def _run(rt, items, llm):
    rt.llm = AgentLLM(llm, rt.redact, rt.log, rt.run_budget)
    rt.items = {i.item_id: i for i in items}
    investigator.run(rt)
    return {i.unit.name: rt.verdicts[i.item_id] for i in items}


def _rules(rt, rule):
    return [e["payload"] for e in rt.log.events if e["payload"].get("rule") == rule]


NAMES = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta"]  # no shared name pattern


def test_candidates_with_the_same_pattern_share_requests_of_at_most_five(rt):
    llm = PerCandidate()
    items = [_item(n) for n in NAMES] + [_item(n, "duplicate") for n in ("copyone", "copytwo")]
    verdicts = _run(rt, items, llm)
    assert sorted(t.count("Candidate ") for t in llm.tasks) == [2, 2, 5]
    assert rt.llm.n == 3 and rt.usage["investigator"]["instances"] == 3
    assert sorted(len(p["items"]) for p in _rules(rt, "batch")) == [2, 2, 5]
    assert {v["stop"] for v in verdicts.values()} == {"final"}


def test_each_candidate_gets_its_own_verdict(rt):
    wanted = {"alpha": "safe", "beta": "drop", "gamma": "suggest"}
    verdicts = _run(rt, [_item(n) for n in wanted], PerCandidate(wanted.get))
    assert {n: v["decision"] for n, v in verdicts.items()} == wanted
    lanes = {i.unit.name: (i.lane, i.action) for i in rt.items.values()}
    assert lanes == {
        "alpha": ("safe", "delete_unit"),
        "beta": ("suggest", "report_only"),
        "gamma": ("suggest", "delete_unit"),
    }
    assert verdicts["alpha"]["evidence"][0]["tool"] == "find_references"


def test_a_malformed_batch_answer_falls_back_to_one_request_per_candidate(rt):
    bad = json.dumps({"final": {"verdicts": "none"}})
    verdicts = _run(
        rt, [_item(n) for n in ("alpha", "beta", "gamma")], PerCandidate(batch_reply=bad)
    )
    assert rt.llm.n == 2 + 3  # the batch and its repair turn, then each candidate alone
    assert all(v["stop"] == "final" and "batch" not in v for v in verdicts.values())


def test_a_missing_or_rule_breaking_verdict_is_asked_alone(rt):
    items = [_item(n) for n in ("alpha", "beta", "gamma")]
    cite = [{"result": "R1", "says": "alpha's references"}]
    answer = [
        {"item_id": items[0].item_id, "decision": "suggest", "reason": "r", "evidence": cite},
        {"item_id": items[1].item_id, "decision": "safe", "reason": "r", "evidence": cite},
    ]  # beta's safe verdict cites only alpha's result; gamma has none
    llm = PerCandidate(lambda name: "safe", json.dumps({"final": {"verdicts": answer}}))
    verdicts = _run(rt, items, llm)
    assert rt.llm.n == 1 + 2
    assert "batch" in verdicts["alpha"] and verdicts["alpha"]["decision"] == "suggest"
    assert "batch" not in verdicts["beta"] and "batch" not in verdicts["gamma"]
    assert verdicts["beta"]["decision"] == verdicts["gamma"]["decision"] == "safe"


def test_a_cautious_verdict_is_reused_for_an_identical_pattern(rt):
    items = [_item(n) for n in ("legacy_one", "legacy_two", "legacy_three")]
    verdicts = _run(rt, items, PerCandidate(lambda name: "suggest"))
    assert rt.llm.n == 1
    source = verdicts["legacy_one"]
    for name in ("legacy_two", "legacy_three"):
        assert verdicts[name]["stop"] == "reused" and verdicts[name]["decision"] == "suggest"
        assert verdicts[name]["reused_from"] == source["item_id"]
    assert [p["from"] for p in _rules(rt, "reuse")] == [source["item_id"]] * 2


def test_a_safe_verdict_is_never_reused(rt):
    items = [_item(n) for n in ("legacy_one", "legacy_two", "legacy_three")]
    verdicts = _run(rt, items, PerCandidate(lambda name: "safe"))
    assert rt.llm.n == 2  # legacy_one alone, then the other two in one batch
    assert {v["stop"] for v in verdicts.values()} == {"final"} and not _rules(rt, "reuse")


def test_off_is_one_request_per_candidate_as_before(rt):
    rt.acfg["investigate_batch"] = False  # YAML's bare off
    items = [_item(n) for n in ("legacy_one", "legacy_two", "alpha")]
    llm = PerCandidate()
    verdicts = _run(rt, items, llm)
    assert rt.llm.n == 3 and all(t.count("Candidate ") == 1 for t in llm.tasks)
    assert not _rules(rt, "batch") and not _rules(rt, "reuse")
    assert all("several candidates" not in m[0]["content"] for m in rt.llm.sent)
    assert {v["stop"] for v in verdicts.values()} == {"final"}


def test_the_setting_is_on_or_off(mini, agent_cfg, tmp_path):
    assert batch_on({}) is False and batch_on({"investigate_batch": True}) is True
    agent_cfg["core"]["agents"]["investigate_batch"] = "sometimes"
    ws, _ = prepare_workspace(mini, tmp_path / "ws", agent_cfg["core"]["sandbox"])
    with pytest.raises(ValueError, match="investigate_batch"):
        Runtime(ws, agent_cfg, None, tmp_path / "out")
