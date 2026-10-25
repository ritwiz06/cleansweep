from bookshelf.inventory import Inventory
from bookshelf.orders import order_total
from bookshelf.reports import stock_report

ISBN = "978-0-13-468599-1"


def make():
    inv = Inventory()
    inv.add(ISBN, "Clean Code", 40.0, 3)
    return inv


def test_order_total_with_tax():
    assert order_total(make(), [(ISBN, 2)], tax_rate=0.08) == 86.4


def test_stock_report():
    report = stock_report(make())
    assert "Clean Code: 3 x $40.00" in report
    assert report.endswith("Total: $120.00")
