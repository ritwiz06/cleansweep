import importlib.util
import signal
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v3" / "methods_v3.py"


def load():
    spec = importlib.util.spec_from_file_location("methods_v3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_label_resolves_to_its_kind_and_overrides():
    methods = load()
    assert methods.resolve("agentic").kind == "agentic"
    assert methods.resolve("agentic-no_resolver").reviewer == {"dynamic_refs": "off"}
    assert methods.resolve("agentic-batch").agents == {"investigate_batch": "on"}
    assert methods.resolve("agentic-thorough").mode == "thorough"
    assert methods.resolve("aider").kind == "external"
    assert methods.resolve("cleansweep").kind == "v1"
    with pytest.raises(ValueError):
        methods.resolve("agentic-unknown")


def test_apply_merges_overrides_into_a_copy():
    methods = load()
    cfg = {
        "core": {"agents": {"mode": "safe", "budget": {"minutes": 60}}},
        "reviewer": {"scope": "repo"},
    }
    out = methods.apply(cfg, methods.resolve("agentic-no_resolver"))
    assert out["reviewer"] == {"scope": "repo", "dynamic_refs": "off"}
    assert out["core"]["agents"]["budget"] == {"minutes": 60}
    thorough = methods.apply(cfg, methods.resolve("agentic-thorough"))
    assert thorough["core"]["agents"]["mode"] == "thorough"
    assert cfg["core"]["agents"]["mode"] == "safe" and "dynamic_refs" not in cfg["reviewer"]


def test_time_cap_raises_capped_and_restores_the_alarm():
    methods = load()
    with pytest.raises(methods.Capped):
        with methods.time_cap(0.001):
            time.sleep(1)
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    with methods.time_cap(1):
        pass
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_every_method_gets_the_same_cap_and_budget():
    methods = load()
    cfg = methods.limits({"core": {"agents": {"budget": {"test_runs": 80}}}})
    assert cfg["core"]["agents"]["budget"] == {
        "test_runs": 80,
        "minutes": methods.CAP_MINUTES,
        "llm_calls": methods.LLM_BUDGET,
    }
    assert cfg["core"]["llm"]["max_calls"] == methods.LLM_BUDGET
    assert cfg["exp"]["external_cap_min"] == methods.CAP_MINUTES
    assert cfg["exp"]["external_llm_budget"] == methods.LLM_BUDGET


def test_a_run_at_the_cap_or_the_budget_is_timed_out():
    methods = load()
    assert methods.timed_out({}, methods.CAP_MINUTES) == "time cap"
    assert methods.timed_out({"llm_calls": methods.LLM_BUDGET}, 10) == "LLM budget"
    assert methods.timed_out({"external": {"stopped": "LLM budget"}}, 10) == "LLM budget"
    assert methods.timed_out({"llm_calls": 3, "agentic": {"stopped": None}}, 10) == ""
