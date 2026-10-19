import pytest

from cleansweep.scheduler import should_sweep


def test_policies():
    assert should_sweep("now", {})
    assert should_sweep("every_pr", {"prs_since_sweep": 1})
    assert not should_sweep("every_n", {"prs_since_sweep": 3, "n": 5})
    assert should_sweep(
        "daily", {"now": "2026-10-20T01:00:00Z", "last_sweep_time": "2026-10-19T23:00:00Z"}
    )
    assert not should_sweep(
        "daily", {"now": "2026-10-19T23:30:00Z", "last_sweep_time": "2026-10-19T23:00:00Z"}
    )
    assert should_sweep("adaptive", {"slop_loc": 30, "repo_loc": 1000})
    with pytest.raises(ValueError):
        should_sweep("weekly", {})
