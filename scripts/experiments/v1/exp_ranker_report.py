"""The ranker as a negative result: what it learns from AIDev removal requests, and why that is
not a safety score.

    python scripts/experiments/v1/exp_ranker_report.py

Repeats the ranker's cross-validation (GroupKFold by repository, the same calibrated model as
ranking/train.py) to get out-of-fold predictions, a reliability table and permutation importance
on each held-out fold (drop in AUC, 5 repeats). Writes results/summary/v1/ranker_report.md. The
Reviewer keeps its category priors; this script changes nothing about that.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cleansweep.core.models import FEATURE_COLUMNS
from cleansweep.data import load_removal_labels
from cleansweep.ranking.train import _model, can_train

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "results" / "summary" / "v1" / "ranker_report.md"


def cross_validate(labels: pd.DataFrame, repeats: int = 5):
    """Out-of-fold probabilities and per-feature permutation importance (mean AUC drop)."""
    from sklearn.inspection import permutation_importance
    from sklearn.model_selection import GroupKFold

    x = labels[FEATURE_COLUMNS].astype(float)
    y = labels.label.astype(int)
    groups = labels.repo_id
    oof = pd.Series(np.nan, index=labels.index)
    drops = []
    for tr, te in GroupKFold(n_splits=min(5, groups.nunique())).split(x, y, groups):
        if y.iloc[tr].nunique() < 2 or y.iloc[te].nunique() < 2:
            continue
        model = _model(int(y.iloc[tr].sum())).fit(x.iloc[tr], y.iloc[tr])
        oof.iloc[te] = model.predict_proba(x.iloc[te])[:, 1]
        imp = permutation_importance(
            model, x.iloc[te], y.iloc[te], scoring="roc_auc", n_repeats=repeats, random_state=0
        )
        drops.append(imp.importances_mean)
    importance = pd.Series(np.mean(drops, axis=0), index=FEATURE_COLUMNS).sort_values(
        ascending=False
    )
    return oof, importance


def _table(rows: list[list], header: list[str]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return lines + ["| " + " | ".join(str(v) for v in r) + " |" for r in rows]


def report(labels: pd.DataFrame) -> str:
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    oof, importance = cross_validate(labels)
    done = oof.notna()
    y, p = labels.label[done].astype(int), oof[done]
    frac, mean_pred = calibration_curve(y, p, n_bins=10, strategy="quantile")
    base = y.mean()
    lines = [
        "# Ranker report: a negative result",
        "",
        f"Trained on {len(labels):,} labeled units from {labels.repo_id.nunique()} AIDev "
        f"repositories; {int(labels.label.sum())} of them are units reviewers asked to remove "
        f"({base:.1%}). Calibrated gradient boosting, GroupKFold by repository (5 folds); all "
        "numbers below are out of fold.",
        "",
        *_table(
            [
                ["AUC", f"{roc_auc_score(y, p):.3f}", "0.5 = chance"],
                [
                    "Average precision",
                    f"{average_precision_score(y, p):.3f}",
                    f"base rate {base:.3f}",
                ],
                [
                    "Brier score",
                    f"{brier_score_loss(y, p):.4f}",
                    f"always predicting {base:.3f}: {base * (1 - base):.4f}",
                ],
            ],
            ["Metric", "Value", "Reference"],
        ),
        "",
        "## Calibration (10 bins of equal size)",
        "",
        *_table(
            [[f"{m:.3f}", f"{f:.3f}"] for m, f in zip(mean_pred, frac, strict=True)],
            ["Mean predicted probability", "Observed share requested"],
        ),
        "",
        f"Out-of-fold predictions have median {p.median():.3f} and maximum {p.max():.3f}: close "
        "to calibrated, but the model barely separates units "
        "(results/figures/v1/ranker_reliability.png).",
        "",
        "## Most important features (permutation importance, mean AUC drop on held-out folds)",
        "",
        *_table(
            [[name, f"{drop:.4f}"] for name, drop in importance.head(5).items()],
            ["Feature", "AUC drop"],
        ),
        "",
        *(
            [
                "Unit size (`loc`) carries most of the signal: longer units get more review "
                "comments, which is about where reviewers look, not about whether code can go.",
                "",
            ]
            if importance.index[0] == "loc"
            else []
        ),
        "## Why it doesn't measure safety",
        "",
        '- The label is "a reviewer asked to remove this unit", not "removing it keeps the '
        "program's behavior\"; reviewers ask to remove code that is used (comments, try/except "
        "blocks, redundant logic), and leave unused code they never look at.",
        '- Most units are never reviewed, so a 0 means "not asked about", not "must be kept"; '
        "the classes are not safe vs. unsafe.",
        f"- The scores are small (median {p.median():.3f}, at most {p.max():.2f}) and on another "
        "scale than the Reviewer's safe-to-apply score, whose batching threshold (0.6) the model "
        "never reaches; the Guard's test and probe outcomes would be the right label for safety.",
        "",
        "The Reviewer therefore keeps its category priors as the default (`exp.ranker_path` "
        "unset).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    labels = load_removal_labels()
    ok, reason = can_train(labels)
    if not ok:
        OUT.write_text(f"# Ranker report\n\nNot trained: {reason}.\n")
        print(reason)
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(report(labels))
    print(OUT.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
