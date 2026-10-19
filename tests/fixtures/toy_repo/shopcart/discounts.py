CODES = {"SAVE10": 0.10, "HALF": 0.50}


def _round_price(value):
    """Round a price to whole cents."""
    if value is None:
        return 0.0
    amount = float(value)
    if amount < 0:
        raise ValueError("price cannot be negative")
    return round(amount, 2)


def apply_discount(amount, code):
    rate = CODES.get(code.upper(), 0.0)
    return _round_price(amount * (1 - rate))
