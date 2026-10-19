def round_price(value):
    """Round a price to whole cents."""
    if value is None:
        return 0.0
    amount = float(value)
    if amount < 0:
        raise ValueError("price cannot be negative")
    return round(amount, 2)


def format_money(value):
    return f"${round_price(value):.2f}"


def format_money_v2(value, currency="USD"):
    amount = round_price(value)
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def slugify(name):
    return "-".join(name.lower().split())
