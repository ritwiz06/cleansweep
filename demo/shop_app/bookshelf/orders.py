from decimal import ROUND_HALF_UP, Decimal

from bookshelf.utils import normalize_isbn


def _half_up(amount):
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _round_money(value):
    """Round an amount to whole cents."""
    if value is None:
        return 0.0
    amount = float(value)
    if amount < 0:
        raise ValueError("amount cannot be negative")
    return _half_up(amount)


def order_total(inventory, lines, tax_rate=0.0):
    subtotal = sum(
        inventory.books[normalize_isbn(isbn)]["price"] * qty for isbn, qty in lines
    )
    return _round_money(subtotal * (1 + tax_rate))
