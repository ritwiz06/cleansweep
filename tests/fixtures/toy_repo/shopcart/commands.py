import sys

from shopcart.storage import load_cart, save_cart
from shopcart.utils import format_money, slugify


def cmd_add(cart, args):
    name, price = args[0], float(args[1])
    qty = int(args[2]) if len(args) > 2 else 1
    cart.add(name, price, qty)
    return f"added {name}"


def cmd_total(cart, args):
    code = args[0] if args else None
    return format_money(cart.checkout(code))


def cmd_export(cart, args):
    path = args[0] if args else f"{slugify('my cart')}.json"
    save_cart(cart, path)
    return f"saved {len(cart.items)} items to {path}"


def cmd_load(cart, args):
    loaded = load_cart(args[0])
    cart.items = loaded.items
    return f"loaded {len(cart.items)} items"
