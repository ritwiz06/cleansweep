from cleansweep.core.models import CleanupItem, CodeUnit
from cleansweep.guard import Guard, verify


def dead(name, path="shopcart/utils.py"):
    return CleanupItem(
        name, CodeUnit(path, "function", name), "dead_code", "delete_unit", "safe", "r"
    )


def test_safe_edit_is_kept(toy_ws):
    guard = Guard(toy_ws, None, {})
    assert guard.check_batch([dead("format_money_v2")])
    assert guard.results()[0].status == "kept"
    assert "-def format_money_v2" in guard.results()[0].diff


def test_getattr_trap_is_rolled_back(toy_ws):
    guard = Guard(toy_ws, None, {})
    head = toy_ws.checkpoint("x")
    assert not guard.check_batch([dead("cmd_export", "shopcart/commands.py")])
    assert guard.results()[0].status == "rolled_back"
    assert toy_ws.diff(head) == ""


def test_repair_fn_gets_one_try(toy_ws):
    calls = []

    def repair(item, log, repo_dir, llm):
        calls.append(log)
        return None

    guard = Guard(toy_ws, None, {}, repair_fn=repair)
    guard.check_batch([dead("cmd_export", "shopcart/commands.py")])
    assert len(calls) == 1 and "test_export" in calls[0]


def test_format_batch_checks_ast(toy_ws):
    item = CleanupItem(
        "f", CodeUnit("shopcart/pricing.py", "file"), "format", "format", "safe", "r"
    )
    guard = Guard(toy_ws, None, {})
    assert guard.check_batch([item])
    assert guard.results()[0].ast_equal is True


def test_verify_identical_fork(toy_ws):
    other = toy_ws.fork()
    ok, info = verify(toy_ws, other, [], None, {})
    assert ok and info["tests"].passed == 15
    other.close()


def dep(name="requests"):
    return CleanupItem(
        name,
        CodeUnit("requirements.txt", "dependency", name),
        "unused_dependency",
        "remove_dependency",
        "safe",
        "r",
    )


def test_dependency_removal_is_checked_statically_on_a_local_workspace(toy_ws):
    guard = Guard(toy_ws, None, {"diff_tests": False})
    assert guard.check_batch([dep()])
    assert guard.results()[0].status == "kept"
    assert guard.results()[0].notes.startswith("checked statically only")


def test_dependency_removal_needs_the_tests_to_pass_without_the_package(toy_ws, monkeypatch):
    from dataclasses import replace

    hidden = []

    def hide(names):
        hidden.extend(names)
        return dict.fromkeys(names, "hidden")

    real = toy_ws.run_tests

    def run_tests(paths=None, timeout=900):
        result = real(paths, timeout)
        if hidden:  # the package is gone and a test needs it
            return replace(result, ok=False, failed=1, failed_ids=["test_needs_requests"])
        return result

    monkeypatch.setattr(toy_ws, "hide_packages", hide)
    monkeypatch.setattr(toy_ws, "restore_packages", hidden.clear)
    monkeypatch.setattr(toy_ws, "run_tests", run_tests)
    guard = Guard(toy_ws, None, {"diff_tests": False})
    assert not guard.check_batch([dep()])
    assert guard.results()[0].status == "rolled_back"
    assert "tests fail without requests" in guard.results()[0].notes
    assert hidden == []  # put back after the check
    # another installed package requires it: it stays installed, so the removal changes nothing
    monkeypatch.setattr(toy_ws, "hide_packages", lambda n: dict.fromkeys(n, "required by pip"))
    runs = toy_ws.test_runs
    assert guard.check_batch([dep()])
    assert guard.results()[0].notes == "verified: still installed (required by pip)"
    assert toy_ws.test_runs == runs + 1  # only the usual run
