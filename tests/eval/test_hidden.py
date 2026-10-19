from cleansweep.eval import run_hidden_checks


def test_hidden_checks_unchanged_for_empty_diff(toy_repo, cfg):
    out = run_hidden_checks(toy_repo, "", cfg)
    assert out["available"] and out["behavior_changed"] is False
    assert out["hidden_before"]["passed"] == 3


def test_hidden_checks_missing(tmp_path, cfg):
    assert run_hidden_checks(str(tmp_path), "", cfg) == {"available": False}
