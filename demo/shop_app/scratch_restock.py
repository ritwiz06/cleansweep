# trying out restock amounts before adding the command
from bookshelf.cli import run
from bookshelf.inventory import Inventory

inv = Inventory()
run(inv, "add 978-0-13-468599-1 Clean_Code 39.99 1")
for n in (1, 5, 10):
    print(run(inv, f"restock 978-0-13-468599-1 {n}"))
