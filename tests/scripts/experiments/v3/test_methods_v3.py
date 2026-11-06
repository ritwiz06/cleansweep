import importlib.util
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
