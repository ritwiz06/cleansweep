import pytest

from cleansweep.eval.stats import bootstrap_ci, mcnemar, wilcoxon


def test_mcnemar_exact():
    assert mcnemar(0, 0) == 1.0
    assert mcnemar(0, 6) == pytest.approx(2 / 64)
    assert mcnemar(3, 3) == 1.0


def test_bootstrap_ci():
    assert bootstrap_ci([2.0, 2.0, 2.0]) == (2.0, 2.0, 2.0)
    mean, lo, hi = bootstrap_ci([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert mean == 5.5 and lo < mean < hi
    assert bootstrap_ci([1, 5, 9]) == bootstrap_ci([1, 5, 9])  # fixed seed


def test_wilcoxon():
    assert wilcoxon([1, 2, 3], [1, 2, 3]) == (0.0, 1.0)
    _, p = wilcoxon([10, 12, 14, 16, 18, 20, 22, 24], [1, 2, 3, 4, 5, 6, 7, 8])
    assert p < 0.05
