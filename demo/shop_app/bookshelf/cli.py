from bookshelf import commands
from bookshelf.inventory import Inventory


def run(inventory, line):
    name, *args = line.split()
    handler = getattr(commands, f"cmd_{name}", None)
    if handler is None:
        return f"unknown command: {name}"
    return handler(inventory, args)


def main(argv=None):
    inventory = Inventory()
    for line in " ".join(argv or []).split(";"):
        if line.strip():
            print(run(inventory, line.strip()))
    return 0
