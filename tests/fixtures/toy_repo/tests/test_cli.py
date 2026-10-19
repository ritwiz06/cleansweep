from shopcart.cart import Cart
from shopcart.cli import main, run


def test_add_and_total(capsys):
    main(["add pen 2.0 2; total"])
    out = capsys.readouterr().out
    assert "added pen" in out
    assert "$4.32" in out


def test_export(tmp_path):
    cart = Cart()
    run(cart, "add pen 1.0")
    msg = run(cart, f"export {tmp_path / 'c.json'}")
    assert msg.startswith("saved 1 items")


def test_unknown_command():
    assert run(Cart(), "fly away") == "unknown command: fly"
