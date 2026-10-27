import numpy as np
import pandas as pd

from cleansweep.core.models import FEATURE_COLUMNS, CleanupItem, CodeUnit
from cleansweep.ranking import load_ranker
from cleansweep.ranking.train import can_train, train_ranker


def labels(n=400, repos=5, seed=0):
    rng = np.random.default_rng(seed)
    x = pd.DataFrame(rng.normal(size=(n, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    y = (x["n_callers"] < -0.8).astype(int)  # a learnable rule
    return x.assign(label=y, repo_id=[f"aidev:o/r{i % repos}" for i in range(n)])


def test_can_train_reasons():
    assert not can_train(labels(100))[0]
    assert "repositories" in can_train(labels(400, repos=2))[1]
    assert can_train(labels())[0]


def test_train_writes_cv_figure_and_a_loadable_model(tmp_path):
    out = train_ranker(labels(), tmp_path / "m.joblib", tmp_path / "cv.csv", tmp_path / "rel.png")
    assert out["trained"] and out["oof_auc"] > 0.8
    assert (tmp_path / "rel.png").exists() and len(pd.read_csv(tmp_path / "cv.csv")) == 5
    ranker = load_ranker(str(tmp_path / "m.joblib"))
    item = CleanupItem(
        "i", CodeUnit("m.py", "function", "f"), "dead_code", "delete_unit", "safe", "r"
    )
    feats = labels(1).drop(columns=["label", "repo_id"]).set_axis(["m.py::f"])
    ranker.score([item], feats)
    assert 0.0 <= item.safe_score <= 1.0
