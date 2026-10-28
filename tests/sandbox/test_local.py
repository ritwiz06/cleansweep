import json
from pathlib import Path


def test_baseline_tests_pass(toy_ws):
    result = toy_ws.run_tests(None)
    assert result.ok and result.passed == 15
    assert toy_ws.test_runs == 1


def test_apply_diff_rollback(toy_ws):
    base = toy_ws.checkpoint("start")
    target = Path(toy_ws.path) / "shopcart" / "utils.py"
    original = target.read_text()
    target.write_text(original + "\nX = 1\n")
    patch = toy_ws.diff(base)
    assert "+X = 1" in patch
    toy_ws.rollback(base)
    assert target.read_text() == original
    assert toy_ws.apply_patch(patch)
    assert "X = 1" in target.read_text()
    assert not toy_ws.apply_patch("garbage")


def test_fork_is_independent(toy_ws):
    other = toy_ws.fork()
    (Path(other.path) / "debug_cart.py").unlink()
    assert (Path(toy_ws.path) / "debug_cart.py").exists()
    other.close()


def test_diff_stats_counts_deleted_files(toy_ws):
    (Path(toy_ws.path) / "debug_cart.py").unlink()
    stats = toy_ws.diff_stats(toy_ws.base)
    assert stats["files_removed"] == 1 and stats["lines_removed"] == 14


def test_install_files_stay_out_of_the_diff(toy_ws):
    info = Path(toy_ws.path) / "shopcart.egg-info"
    info.mkdir()
    (info / "PKG-INFO").write_text("Name: shopcart\n")
    assert toy_ws.diff(toy_ws.base) == ""


def test_coverage_json_has_contexts(toy_ws):
    path = toy_ws.coverage_json()
    data = json.loads(Path(path).read_text())
    contexts = data["files"]["shopcart/cart.py"]["contexts"]
    assert any("test_add_and_count" in c for ctx in contexts.values() for c in ctx)


def test_junit_statuses_and_last_statuses(toy_ws, tmp_path):
    from cleansweep.sandbox.workspace import junit_statuses

    xml = tmp_path / "junit.xml"
    xml.write_text(
        '<testsuite><testcase classname="t" name="a"/>'
        '<testcase classname="t" name="b"><failure/></testcase>'
        '<testcase classname="t" name="c"><error/></testcase>'
        '<testcase classname="t" name="d"><skipped/></testcase></testsuite>'
    )
    assert junit_statuses(xml) == {
        "t::a": "passed",
        "t::b": "failed",
        "t::c": "error",
        "t::d": "skipped",
    }
    toy_ws.run_tests(None)
    assert toy_ws.last_statuses and set(toy_ws.last_statuses.values()) <= {"passed", "skipped"}
