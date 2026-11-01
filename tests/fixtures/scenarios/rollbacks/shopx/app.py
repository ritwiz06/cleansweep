import shopx.formats
from shopx.registry import FORMATS


def export(fmt, rows):
    return FORMATS[fmt](rows)
