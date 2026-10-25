import pytest

from bookshelf.inventory import Inventory

ISBN = "978-0-13-468599-1"


def test_add_merges_copies():
    inv = Inventory()
    inv.add(ISBN, "Clean Code", 39.99, 2)
    inv.add("9780134685991", "Clean Code", 39.99, 1)
    assert inv.books["9780134685991"]["copies"] == 3


def test_remove_never_goes_below_zero():
    inv = Inventory()
    inv.add(ISBN, "Clean Code", 39.99, 1)
    inv.remove(ISBN, 5)
    assert inv.books["9780134685991"]["copies"] == 0


def test_find_and_stock_value():
    inv = Inventory()
    inv.add(ISBN, "Clean Code", 40.0, 2)
    inv.add("0-201-63361-2", "Design Patterns", 50.0, 1)
    assert inv.find("code") == ["Clean Code"]
    assert inv.stock_value() == 130.0


def test_bad_isbn():
    with pytest.raises(ValueError):
        Inventory().add("123", "Short", 1.0)
