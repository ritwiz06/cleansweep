# Hidden checks for the demo app. The Guard never sees these; only evaluation runs them.
from bookshelf.cli import run
from bookshelf.inventory import Inventory
from bookshelf.orders import order_total


def test_order_total_rounds_half_up():
    inv = Inventory()
    inv.add("0-201-63361-2", "Pamphlet", 0.125, 1)
    assert order_total(inv, [("0-201-63361-2", 1)]) == 0.13


def test_save_and_load_commands(tmp_path):
    inv = Inventory()
    run(inv, "add 0-201-63361-2 Design_Patterns 50 2")
    assert run(inv, f"save {tmp_path / 'books.json'}") == "saved 1 books"
    other = Inventory()
    assert run(other, f"load {tmp_path / 'books.json'}") == "loaded 1 books"
    assert other.books["0201633612"]["copies"] == 2


def test_order_total_for_two_titles():
    inv = Inventory()
    inv.add("0-201-63361-2", "Design Patterns", 50.0, 3)
    inv.add("978-0-13-468599-1", "Clean Code", 39.99, 3)
    assert order_total(inv, [("0-201-63361-2", 1), ("978-0-13-468599-1", 2)]) == 129.98
