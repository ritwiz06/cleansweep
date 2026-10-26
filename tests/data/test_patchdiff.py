import json

import pytest

from cleansweep.data import patchdiff


@pytest.fixture
def pd_cfg(tmp_path, monkeypatch):
    tools = tmp_path / "pd" / "data" / "tool_results" / "sub_a"
    tools.mkdir(parents=True)
    (tools / "results.json").write_text(json.dumps({"resolved": ["x__x-1", "x__x-2", "x__x-3"]}))
    preds = [
        {"instance_id": "x__x-1", "model_patch": "diff 1"},
        {"instance_id": "x__x-2", "model_patch": "diff 2"},
        {"instance_id": "x__x-3", "model_patch": "diff 3"},
        {"instance_id": "x__x-9", "model_patch": "not resolved"},
    ]
    (tools / "all_preds.jsonl").write_text("\n".join(json.dumps(p) for p in preds))
    results = tmp_path / "zenodo" / "extracted" / "PatchDiff" / "results"
    results.mkdir(parents=True)
    tested = {
        "x__x-1": [
            {"idx": 0, "gen_test_file": "def test_a(): pass\n", "differential_tests": []},
            {"idx": 1, "gen_test_file": "def test_b(): pass\n", "differential_tests": ["t::b"]},
        ],
        "x__x-2": [{"idx": 0, "gen_test_file": "def test_c(): pass\n", "differential_tests": []}],
    }
    (results / "RQ2_agent_a_difftests.json").write_text(json.dumps(tested))
    (results / "RQ1_agent_a_runall.json").write_text(json.dumps({}))
    cfg = {
        "dir": str(tmp_path / "pd"),
        "results_dir": str(tmp_path / "zenodo"),
        "index": str(tmp_path / "processed" / "index.json"),
        "tests_dir": str(tmp_path / "processed" / "tests"),
        "max_hidden_tests": 10,
        "agents": {"agent_a": "sub_a"},
    }
    monkeypatch.setattr(patchdiff, "_cfg", lambda: cfg)
    return cfg


def test_index_labels_and_orders_hidden_tests(pd_cfg):
    index = patchdiff.build_index(pd_cfg)
    one = index["agent_a/x__x-1"]
    assert one["differs_from_oracle"] is True and one["n_revealing_tests"] == 1
    assert one["hidden_tests"][0].endswith("test_patchdiff_1.py")  # the revealing test first
    assert index["agent_a/x__x-2"]["differs_from_oracle"] is False


def test_loader_returns_plausible_patches_only(pd_cfg):
    patchdiff.build_index(pd_cfg)
    patches = {p.instance_id: p for p in patchdiff.load_agent_patches()}
    assert set(patches) == {"x__x-1", "x__x-2", "x__x-3"}
    assert (
        patches["x__x-1"].differs_from_oracle is True and len(patches["x__x-1"].hidden_tests) == 2
    )
    assert patches["x__x-3"].differs_from_oracle is None and patches["x__x-3"].hidden_tests == []
