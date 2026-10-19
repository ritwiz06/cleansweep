# quick check for the discount rounding issue
from shopcart.cart import Cart

cart = Cart()
cart.add("pen", 1.99, 3)
print(cart.checkout("SAVE10"))
