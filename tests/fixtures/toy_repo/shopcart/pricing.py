from shopcart.utils import round_price
TAX_RATE=0.08
def subtotal( items ):
    return round_price(sum(item['price']*item['qty'] for item in items))
def tax(items, rate = TAX_RATE):
    return round_price( subtotal(items)*rate )
def total(items):
    return round_price(subtotal(items)+tax(items))
