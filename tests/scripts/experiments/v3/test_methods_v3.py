import importlib.util
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v3" / "methods_v3.py"


def load():
    spec = importlib.util.spec_from_file_location("methods_v3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_aider_is_one_more_method_and_runs_through_exp_external(monkeypatch):
    methods = load()
    assert methods.LABELS[-1] == "aider" and "agentic-adaptive" in methods.LABELS
    assert methods.resolve("aider") == ("aider", None, {})
    assert methods.resolve("agentic-adaptive") == ("agentic", None, {"investigate": "adaptive"})
    import exp_external

    calls = []
    monkeypatch.setattr(
        exp_external, "run_external", lambda t, c, s: calls.append(("aider", t, s)) or "aider"
    )
    monkeypatch.setattr(
        methods, "run_sweep_v2", lambda t, c, m, s, e: calls.append((m, t, s)) or "v2"
    )
    assert methods.run_sweep("target_a", {}, "aider", 2) == "aider"
    assert methods.run_sweep("target_a", {}, method="agentic", seed=1) == "v2"
    assert calls == [("aider", "target_a", 2), ("agentic", "target_a", 1)]


def test_plug_gives_a_runner_the_v3_methods():
    methods = load()
    runner = types.ModuleType("runner_a")
    runner.LABELS, runner.resolve, runner.run_sweep = ["agentic"], None, None
    methods.plug(runner)
    assert "aider" in runner.LABELS
    assert runner.resolve is methods.resolve and runner.run_sweep is methods.run_sweep
