from shopcart import pricing
from shopcart.utils import format_money, round_price, slugify

ITEMS = [{"name": "a", "price": 3.0, "qty": 2}, {"name": "b", "price": 4.0, "qty": 1}]


def test_subtotal_and_tax():
    assert pricing.subtotal(ITEMS) == 10.0
    assert pricing.tax(ITEMS) == 0.8


def test_total():
    assert pricing.total(ITEMS) == 10.8


def test_round_price():
    assert round_price(3.333) == 3.33
    assert round_price(None) == 0.0


def test_format_money_and_slugify():
    assert format_money(5) == "$5.00"
    assert slugify("My Cart") == "my-cart"
