FORMATS = {}


def register(name, fn):
    FORMATS[name] = fn
