import pytest

from cleansweep.data.swebench import _as_list, to_task


def test_row_to_task():
    row = {
        "instance_id": "o__r-1",
        "repo": "o/r",
        "base_commit": "abc",
        "patch": "p",
        "test_patch": "t",
        "FAIL_TO_PASS": '["a::b"]',
        "PASS_TO_PASS": ["c::d"],
        "version": 1.0,
    }
    row["FAIL_TO_PASS"] = _as_list(row["FAIL_TO_PASS"])
    task = to_task(row)
    assert task.fail_to_pass == ["a::b"] and task.pass_to_pass == ["c::d"]
    assert task.oracle_patch == "p" and task.version == "1.0"


@pytest.mark.network
def test_load_tasks_has_500():
    from cleansweep.data import load_tasks

    assert len(load_tasks()) == 500
