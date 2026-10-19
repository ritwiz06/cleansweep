from shopcart.discounts import apply_discount


def test_known_code():
    assert apply_discount(100.0, "HALF") == 50.0


def test_unknown_code():
    assert apply_discount(20.0, "NOPE") == 20.0
