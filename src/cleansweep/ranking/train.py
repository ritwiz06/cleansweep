"""Train the ranker on AIDev removal labels: gradient boosting, calibrated, cross-validated by repo.

LightGBM needs the system OpenMP library (libomp), which is not available in our venv-only
setup, so this uses scikit-learn's histogram gradient boosting, the same kind of model.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cleansweep.core.models import FEATURE_COLUMNS

MIN_ROWS = 300
MIN_POSITIVES = 20


def can_train(labels: pd.DataFrame) -> tuple[bool, str]:
    """Enough labeled rows, both classes, and more than one repository for grouped CV."""
    if len(labels) < MIN_ROWS:
        return False, f"only {len(labels)} labeled rows (need {MIN_ROWS})"
    pos = int(labels.label.sum())
    if pos < MIN_POSITIVES or pos == len(labels):
        return (
            False,
            f"{pos} removal requests among {len(labels)} rows "
            f"(need {MIN_POSITIVES}+ of each class)",
        )
    if labels.repo_id.nunique() < 3:
        return False, f"only {labels.repo_id.nunique()} repositories (need 3 for grouped CV)"
    return True, ""


def _model(n_pos: int):
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import HistGradientBoostingClassifier

    base = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=0)
    method = "isotonic" if n_pos >= 100 else "sigmoid"
    return CalibratedClassifierCV(base, method=method, cv=3)


def train_ranker(
    labels: pd.DataFrame, model_path: str | Path, cv_path: str | Path, fig_path: str | Path
) -> dict:
    """GroupKFold by repository: per-fold AUC, average precision and Brier score to cv_path, a
    reliability figure to fig_path, and the model fit on all rows to model_path (joblib)."""
    import joblib
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    from sklearn.model_selection import GroupKFold

    ok, reason = can_train(labels)
    if not ok:
        return {"trained": False, "reason": reason}
    x = labels[FEATURE_COLUMNS].astype(float)
    y = labels.label.astype(int)
    groups = labels.repo_id
    folds = min(5, groups.nunique())
    oof = pd.Series(index=labels.index, dtype=float)
    rows = []
    for k, (tr, te) in enumerate(GroupKFold(n_splits=folds).split(x, y, groups)):
        if y.iloc[tr].nunique() < 2:
            continue
        model = _model(int(y.iloc[tr].sum())).fit(x.iloc[tr], y.iloc[tr])
        p = model.predict_proba(x.iloc[te])[:, 1]
        oof.iloc[te] = p
        both = y.iloc[te].nunique() == 2
        rows.append(
            {
                "fold": k,
                "test_repos": groups.iloc[te].nunique(),
                "test_rows": len(te),
                "test_positives": int(y.iloc[te].sum()),
                "auc": round(roc_auc_score(y.iloc[te], p), 3) if both else "",
                "average_precision": round(average_precision_score(y.iloc[te], p), 3)
                if both
                else "",
                "brier": round(brier_score_loss(y.iloc[te], p), 4),
            }
        )
    pd.DataFrame(rows).to_csv(cv_path, index=False)
    done = oof.notna()
    frac, mean_pred = calibration_curve(y[done], oof[done], n_bins=10, strategy="quantile")
    _reliability_figure(frac, mean_pred, fig_path)
    final = _model(int(y.sum())).fit(x, y)
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, model_path)
    return {
        "trained": True,
        "rows": len(labels),
        "positives": int(y.sum()),
        "repos": int(groups.nunique()),
        "oof_auc": round(roc_auc_score(y[done], oof[done]), 3),
        "oof_brier": round(brier_score_loss(y[done], oof[done]), 4),
    }


def _reliability_figure(frac, mean_pred, path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(3.4, 3.2), facecolor="#fcfcfb")
    # removal requests are rare, so zoom to the range the predictions cover
    lim = min(1.0, max(max(frac, default=0), max(mean_pred, default=0), 0.01) * 1.15)
    ax.plot([0, lim], [0, lim], color="#c3c2b7", lw=1, ls="--", label="perfect calibration")
    ax.plot(mean_pred, frac, color="#2a78d6", lw=2, marker="o", ms=4, label="ranker (out of fold)")
    ax.set_xlabel("predicted probability of a removal request", fontsize=8)
    ax.set_ylabel("observed share", fontsize=8)
    ax.set_title("Ranker reliability", loc="left", fontsize=10)
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.tick_params(labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(fontsize=7, frameon=False)
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)
