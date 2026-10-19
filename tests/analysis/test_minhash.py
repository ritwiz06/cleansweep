from cleansweep.analysis import find_duplicates
from cleansweep.analysis.minhash import body_text


def test_finds_exact_and_near_duplicates(toy_repo):
    pairs = {frozenset((a.key, b.key)): s for a, b, s in find_duplicates(toy_repo)}
    exact = frozenset(("shopcart/discounts.py::_round_price", "shopcart/utils.py::round_price"))
    near = frozenset(("shopcart/storage.py::_safe_round", "shopcart/utils.py::round_price"))
    assert pairs[exact] == 1.0
    assert 0.8 <= pairs[near] < 1.0


def test_body_text_ignores_docstring(toy_repo):
    from cleansweep.core.models import CodeUnit

    text = body_text(toy_repo, CodeUnit("shopcart/utils.py", "function", "round_price"))
    assert text.startswith("if value is None")
