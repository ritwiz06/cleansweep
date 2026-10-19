import os

from shopcart import pricing
from shopcart.discounts import apply_discount


def compute_total(items):
    return pricing.total(items)


class Cart:
    def __init__(self):
        self.items = []

    def add(self, name, price, qty=1):
        if qty <= 0:
            raise ValueError("quantity must be positive")
        self.items.append({"name": name, "price": price, "qty": qty})

    def remove(self, name):
        self.items = [item for item in self.items if item["name"] != name]

    def count(self):
        return sum(item["qty"] for item in self.items)

    def checkout(self, code=None):
        amount = compute_total(self.items)
        if code:
            amount = apply_discount(amount, code)
        return amount
