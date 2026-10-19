import json
from decimal import ROUND_HALF_UP, Decimal

from shopcart.cart import Cart


def _half_up(amount):
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _safe_round(value):
    """Round a price to whole cents."""
    if value is None:
        return 0.0
    amount = float(value)
    if amount < 0:
        raise ValueError("price cannot be negative")
    return _half_up(amount)


def save_cart(cart, path):
    data = {
        "items": cart.items,
        "total": _safe_round(sum(i["price"] * i["qty"] for i in cart.items)),
    }
    with open(path, "w") as f:
        json.dump(data, f)


def load_cart(path):
    with open(path) as f:
        data = json.load(f)
    cart = Cart()
    for item in data["items"]:
        cart.add(item["name"], item["price"], item["qty"])
    return cart


def load_legacy(text):
    # old exports were written as Python literals
    data = eval(text)
    cart = Cart()
    for name, price, qty in data:
        cart.add(name, price, qty)
    return cart
