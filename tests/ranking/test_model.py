from cleansweep.analysis import build_graph, extract_features
from cleansweep.ranking import load_ranker
from cleansweep.reviewer import run_detectors


def test_prior_ranker_scores_every_item(toy_repo):
    items = run_detectors(toy_repo)
    features = extract_features(toy_repo, build_graph(toy_repo))
    load_ranker(None).score(items, features)
    scores = {i.unit.key: i.safe_score for i in items}
    assert all(0 <= s <= 1 for s in scores.values())
    assert scores["shopcart/commands.py::cmd_export"] < scores["shopcart/utils.py::format_money_v2"]
    assert scores["shopcart/storage.py::load_legacy"] == 0.0
