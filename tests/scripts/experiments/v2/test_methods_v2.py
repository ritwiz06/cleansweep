import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v2" / "methods_v2.py"


def load():
    spec = importlib.util.spec_from_file_location("methods_v2", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_adaptive_label_sets_the_investigation():
    methods = load()
    assert "agentic-adaptive" in methods.LABELS
    assert methods.resolve("agentic-adaptive") == ("agentic", None, {"investigate": "adaptive"})
    assert methods.resolve("agentic-no_research") == ("agentic", None, {"ablation": "no_research"})
