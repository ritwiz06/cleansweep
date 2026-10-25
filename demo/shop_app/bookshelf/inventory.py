from bookshelf.utils import normalize_isbn, round_money


class Inventory:
    def __init__(self):
        self.books = {}

    def add(self, isbn, title, price, copies=1):
        key = normalize_isbn(isbn)
        if key in self.books:
            self.books[key]["copies"] += copies
        else:
            self.books[key] = {"title": title, "price": price, "copies": copies}
        return key

    def remove(self, isbn, copies=1):
        book = self.books[normalize_isbn(isbn)]
        book["copies"] = max(book["copies"] - copies, 0)

    def find(self, text):
        text = text.lower()
        return sorted(
            b["title"] for b in self.books.values() if text in b["title"].lower()
        )

    def stock_value(self):
        return round_money(sum(b["price"] * b["copies"] for b in self.books.values()))
