from bookshelf.utils import money


def _clean_isbn(raw):
    """Strip dashes and spaces from an ISBN and check its length."""
    if raw is None:
        raise ValueError("missing ISBN")
    digits = raw.replace("-", "").replace(" ", "")
    if len(digits) not in (10, 13):
        raise ValueError(f"bad ISBN: {raw}")
    return digits.upper()


def stock_line(inventory, isbn):
    book = inventory.books[_clean_isbn(isbn)]
    return f"{book['title']}: {book['copies']} x {money(book['price'])}"


def stock_report(inventory):
    lines = [stock_line(inventory, isbn) for isbn in sorted(inventory.books)]
    lines.append(f"Total: {money(inventory.stock_value())}")
    return "\n".join(lines)
