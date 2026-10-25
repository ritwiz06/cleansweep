from bookshelf.utils import round_money


class Inventory:
    def __init__(self):
        self.books = []

    def add(self, isbn, title, price, copies=1):
        self.books.append(
            {"isbn": isbn, "title": title, "price": price, "copies": copies}
        )

    def stock_value(self):
        total = 0
        for book in self.books:
            total = total + book["price"] * book["copies"]
        return round_money(total)
