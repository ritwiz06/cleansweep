import importlib


def _loads(name):
    try:
        importlib.import_module("pkg2." + name)
        return True
    except ImportError:
        return False


def test_one_old_module_remains():
    assert _loads("shapes" + "_old") or _loads("colors" + "_old")
