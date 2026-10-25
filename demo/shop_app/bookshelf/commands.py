from bookshelf.orders import order_total
from bookshelf.reports import stock_report
from bookshelf.storage import load, save
from bookshelf.utils import normalize_isbn


def cmd_add(inventory, args):
    isbn, title, price = args[0], args[1].replace("_", " "), float(args[2])
    copies = int(args[3]) if len(args) > 3 else 1
    return f"added {inventory.add(isbn, title, price, copies)}"


def cmd_restock(inventory, args):
    copies = int(args[1]) if len(args) > 1 else 5
    inventory.books[normalize_isbn(args[0])]["copies"] += copies
    return f"restocked {args[0]} (+{copies})"


def cmd_report(inventory, args):
    return stock_report(inventory)


def cmd_order(inventory, args):
    lines = [(isbn, int(qty)) for isbn, qty in (a.split("x") for a in args)]
    return f"total {order_total(inventory, lines):.2f}"


def cmd_save(inventory, args):
    save(inventory, args[0])
    return f"saved {len(inventory.books)} books"


def cmd_load(inventory, args):
    inventory.books = load(args[0]).books
    return f"loaded {len(inventory.books)} books"
