from bookshelf.utils import money, normalize_isbn, round_money


def test_normalize_isbn():
    assert normalize_isbn("0-201-63361-2") == "0201633612"


def test_round_money_and_money():
    assert round_money(3.333) == 3.33
    assert round_money(None) == 0.0
    assert money(1234.5) == "$1,234.50"
