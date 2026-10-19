from shopcart import commands
from shopcart.cart import Cart


def run(cart, line):
    name, *args = line.split()
    handler = getattr(commands, f"cmd_{name}", None)
    if handler is None:
        return f"unknown command: {name}"
    return handler(cart, args)


def main(argv=None):
    cart = Cart()
    lines = " ".join(argv or []).split(";")
    for line in lines:
        if line.strip():
            print(run(cart, line.strip()))
    return 0
