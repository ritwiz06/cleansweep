# Hidden checks for the toy repo. The Guard never sees these; only evaluation runs them.
import json

from shopcart.cart import Cart
from shopcart.cli import run
from shopcart.storage import save_cart


def test_saved_total_rounds_half_up(tmp_path):
    cart = Cart()
    cart.add("gum", 0.125, 1)
    path = tmp_path / "c.json"
    save_cart(cart, path)
    assert json.loads(path.read_text())["total"] == 0.13


def test_load_command_round_trip(tmp_path):
    cart = Cart()
    run(cart, "add pen 2.0 3")
    run(cart, f"export {tmp_path / 'c.json'}")
    other = Cart()
    assert run(other, f"load {tmp_path / 'c.json'}") == "loaded 1 items"
    assert other.count() == 3


def test_total_command_with_code():
    cart = Cart()
    run(cart, "add book 10 1")
    assert run(cart, "total HALF") == "$5.40"
