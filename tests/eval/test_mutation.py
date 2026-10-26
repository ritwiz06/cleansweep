import ast

from cleansweep.eval.mutation import OPERATORS, mutants, sample

SOURCE = '''import math  # a comment that must survive


def score(a, b, items):
    """Docstring."""
    if a < b and b > 0:
        total = a + 1
    else:
        total = b - 2
    return total if items else math.floor(total)
'''


def test_every_operator_applies_and_only_changes_one_node():
    found = mutants(SOURCE, "m.py", "score")
    assert {m.operator for m in found} == set(OPERATORS)
    for m in found:
        assert ast.dump(ast.parse(m.source)) != ast.dump(ast.parse(SOURCE))
        assert "# a comment that must survive" in m.source
        changed = [
            a for a, b in zip(SOURCE.splitlines(), m.source.splitlines(), strict=True) if a != b
        ]
        assert len(changed) == 1, (m.operator, changed)


def test_examples_of_each_operator():
    by_op = {}
    for m in mutants(SOURCE, "m.py", "score"):
        by_op.setdefault(m.operator, []).append(m.source)
    assert any("(a >= b)" in s for s in by_op["flip_comparison"])
    assert any("(a - 1)" in s for s in by_op["swap_add_sub"])
    assert any("b - 3" in s for s in by_op["int_plus_one"])
    assert any("(a < b or b > 0)" in s for s in by_op["swap_and_or"])
    assert any("return None" in s for s in by_op["return_none"])


def test_sample_spreads_over_operators_and_is_reproducible():
    found = mutants(SOURCE, "m.py", "score")
    picked = sample(found, 5, seed=1)
    assert len({m.operator for m in picked}) == 5
    assert [m.source for m in picked] == [m.source for m in sample(found, 5, seed=1)]
    assert mutants(SOURCE, "m.py", "missing") == []
