import json

from shopcart.cart import Cart
from shopcart.storage import load_cart, save_cart


def test_save_and_load(tmp_path):
    cart = Cart()
    cart.add("pen", 1.5, 2)
    path = tmp_path / "cart.json"
    save_cart(cart, path)
    assert json.loads(path.read_text())["total"] == 3.0
    assert load_cart(path).count() == 2
