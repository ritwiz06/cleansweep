import importlib.util
import json
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


def test_targets_for_swebench_and_aidev_entries():
    runner = load_runner()
    swe = [{"instance_id": "a__b-1", "agent": "agent_a"}]
    assert runner.targets(swe) == [("swebench:a__b-1:agent_a", "a__b-1__agent_a")]
    aidev = [
        {"full_name": "o/slow", "head_sha": "s1", "test_seconds": 90},
        {"full_name": "o/fast", "head_sha": "s2", "test_seconds": "3"},
    ]
    assert runner.targets(aidev) == [("aidev:o/fast@s2", "o__fast"), ("aidev:o/slow@s1", "o__slow")]


def test_hidden_only_reruns_reports_whose_diff_did_not_apply(tmp_path, monkeypatch):
    runner = load_runner()
    calls = []

    def fake_hidden(target, diff, cfg):
        calls.append((target, diff))
        return {"available": True, "applied": True, "behavior_changed": False}

    monkeypatch.setattr(runner, "run_hidden_checks", fake_hidden)
    stuck = tmp_path / "o__fast__tools_only.json"
    stuck.write_text(json.dumps({"stats": {"final_diff": "d", "hidden": {"applied": False}}}))
    ran = tmp_path / "o__fast__one_shot_llm.json"
    ran.write_text(json.dumps({"stats": {"final_diff": "e", "hidden": {"applied": True}}}))
    tier = tmp_path / "tier.json"
    tier.write_text(json.dumps([{"full_name": "o/fast", "head_sha": "s2", "test_seconds": 3}]))
    assert runner.main(["--tier", str(tier), "--out", str(tmp_path), "--hidden-only"]) == 0
    assert calls == [("aidev:o/fast@s2", "d")]
    hidden = json.loads(stuck.read_text())["stats"]["hidden"]
    assert hidden["applied"] is True and hidden["rerun"] is True
    assert json.loads(ran.read_text())["stats"]["hidden"] == {"applied": True}


def test_aidev_runs_stop_without_the_cached_history(tmp_path, monkeypatch, capsys):
    runner = load_runner()
    tier = tmp_path / "tier.json"
    tier.write_text(json.dumps([{"full_name": "o/fast", "head_sha": "s2", "test_seconds": 3}]))
    monkeypatch.setattr(runner, "agent_history", lambda name, sha=None: (set(), None))
    assert runner.main(["--tier", str(tier), "--out", str(tmp_path / "out")]) == 2
    assert "o/fast" in capsys.readouterr().err
    # a cached history without agent commits still runs (no scope, by the data)
    monkeypatch.setattr(runner, "agent_history", lambda name, sha=None: (set(), "c0"))
    assert runner.missing_history(runner.targets(json.loads(tier.read_text()))) == []
