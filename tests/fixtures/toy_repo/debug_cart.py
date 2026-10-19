from shopcart.cart import Cart
from shopcart.pricing import subtotal, tax


def dump(cart):
    for item in cart.items:
        print(item)
    print("subtotal", subtotal(cart.items), "tax", tax(cart.items))


if __name__ == "__main__":
    c = Cart()
    c.add("book", 12.5, 2)
    dump(c)
