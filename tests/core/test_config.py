from cleansweep.core.config import load_config
from cleansweep.core.registry import use_stub


def test_load_config_sections_and_overrides():
    cfg = load_config({"core": {"guard": {"repair": False}}})
    assert set(cfg) >= {"core", "data", "exp", "reviewer"}
    assert cfg["core"]["guard"]["repair"] is False
    assert "max_targets" in cfg["core"]["guard"]


def test_use_stub(monkeypatch):
    monkeypatch.setenv("CLEANSWEEP_STUBS", "analysis, guard")
    assert use_stub("guard") and not use_stub("llm")
    monkeypatch.setenv("CLEANSWEEP_STUBS", "all")
    assert use_stub("llm")
