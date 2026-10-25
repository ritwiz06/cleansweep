def normalize_isbn(raw):
    """Strip dashes and spaces from an ISBN and check its length."""
    if raw is None:
        raise ValueError("missing ISBN")
    digits = raw.replace("-", "").replace(" ", "")
    if len(digits) not in (10, 13):
        raise ValueError(f"bad ISBN: {raw}")
    return digits.upper()


def round_money(value):
    """Round an amount to whole cents."""
    if value is None:
        return 0.0
    amount = float(value)
    if amount < 0:
        raise ValueError("amount cannot be negative")
    return round(amount, 2)


def money(value):
    return f"${round_money(value):,.2f}"


def isbn_checksum_ok(digits):
    if len(digits) != 13:
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == int(digits[12])
