from bookshelf.cli import main, run
from bookshelf.inventory import Inventory

ISBN = "978-0-13-468599-1"


def test_add_and_report(capsys):
    main([f"add {ISBN} Clean_Code 40 2; report"])
    out = capsys.readouterr().out
    assert "added 9780134685991" in out
    assert "Total: $80.00" in out


def test_restock():
    inv = Inventory()
    run(inv, f"add {ISBN} Clean_Code 40 1")
    assert run(inv, f"restock {ISBN} 3") == f"restocked {ISBN} (+3)"
    assert inv.books["9780134685991"]["copies"] == 4


def test_order_and_unknown_command():
    inv = Inventory()
    run(inv, f"add {ISBN} Clean_Code 40 5")
    assert run(inv, f"order {ISBN}x2") == "total 80.00"
    assert run(inv, "fly away") == "unknown command: fly"
