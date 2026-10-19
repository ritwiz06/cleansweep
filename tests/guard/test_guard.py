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
