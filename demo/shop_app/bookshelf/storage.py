import json

from bookshelf.inventory import Inventory


def save(inventory, path):
    with open(path, "w") as f:
        json.dump(inventory.books, f)


def load(path):
    inventory = Inventory()
    with open(path) as f:
        inventory.books = json.load(f)
    return inventory


def load_legacy(text):
    # catalogs from the old system were saved as Python literals
    rows = eval(text)
    inventory = Inventory()
    for isbn, title, price, copies in rows:
        inventory.add(isbn, title, price, copies)
    return inventory
