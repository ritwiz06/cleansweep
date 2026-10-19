import pytest

from shopcart.cart import Cart


def test_add_and_count():
    cart = Cart()
    cart.add("pen", 2.0, 3)
    cart.add("book", 10.0)
    assert cart.count() == 4


def test_add_rejects_zero_quantity():
    with pytest.raises(ValueError):
        Cart().add("pen", 2.0, 0)


def test_remove():
    cart = Cart()
    cart.add("pen", 2.0)
    cart.add("book", 10.0)
    cart.remove("pen")
    assert [i["name"] for i in cart.items] == ["book"]


def test_checkout_with_tax():
    cart = Cart()
    cart.add("book", 10.0, 2)
    assert cart.checkout() == 21.6


def test_checkout_with_code():
    cart = Cart()
    cart.add("book", 10.0, 2)
    assert cart.checkout("save10") == 19.44
