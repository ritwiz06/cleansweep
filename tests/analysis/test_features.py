from cleansweep.analysis import build_graph, extract_features
from cleansweep.core.models import FEATURE_COLUMNS


def test_feature_table_complete(toy_repo):
    df = extract_features(toy_repo, build_graph(toy_repo))
    assert list(df.columns) == FEATURE_COLUMNS
    assert not df.isna().any().any()
    assert df.loc["shopcart/cart.py::compute_total", "is_wrapper"] == 1
    assert df.loc["shopcart/pricing_old.py", "name_pattern_score"] == 1.0
    assert df.loc["shopcart/discounts.py::_round_price", "max_dup_similarity"] == 1.0
