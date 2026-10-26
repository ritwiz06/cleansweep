import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "exp_swebench.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("exp_swebench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_results_need_resume(tmp_path, capsys):
    runner = load_runner()
    (tmp_path / "x__agent_a__tools_only.json").write_text("{}")
    tier = tmp_path / "tier.json"
    tier.write_text("[]")
    assert runner.main(["--tier", str(tier), "--out", str(tmp_path)]) == 2
    assert "--resume" in capsys.readouterr().err
    assert runner.main(["--tier", str(tier), "--out", str(tmp_path), "--resume"]) == 0
    assert "finished" in (tmp_path / "log.txt").read_text()


def test_every_method_maps_to_a_sweep_method():
    from cleansweep.core.models import METHODS

    runner = load_runner()
    assert set(runner.METHODS) >= {"one_shot_llm", "tools_only", "guard_tests_only"}
    assert all(method in METHODS for method, _ in runner.METHODS.values())
