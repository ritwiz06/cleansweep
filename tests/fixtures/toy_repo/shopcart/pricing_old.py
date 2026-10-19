from shopcart.utils import round_price

TAX_RATE = 0.075


def subtotal(items):
    result = 0
    for item in items:
        result = result + item["price"] * item["qty"]
    return round_price(result)


def total(items):
    return round_price(subtotal(items) * (1 + TAX_RATE))
