# Ranker report: a negative result

Trained on 9,416 labeled units from 79 AIDev repositories; 262 of them are units reviewers asked to remove (2.8%). Calibrated gradient boosting, GroupKFold by repository (5 folds); all numbers below are out of fold.

| Metric | Value | Reference |
|---|---|---|
| AUC | 0.607 | 0.5 = chance |
| Average precision | 0.047 | base rate 0.028 |
| Brier score | 0.0269 | always predicting 0.028: 0.0271 |

## Calibration (10 bins of equal size)

| Mean predicted probability | Observed share requested |
|---|---|
| 0.010 | 0.020 |
| 0.017 | 0.020 |
| 0.020 | 0.012 |
| 0.022 | 0.026 |
| 0.024 | 0.021 |
| 0.027 | 0.030 |
| 0.029 | 0.030 |
| 0.035 | 0.025 |
| 0.043 | 0.031 |
| 0.062 | 0.066 |

Out-of-fold predictions have median 0.026 and maximum 0.202: close to calibrated, but the model barely separates units (results/figures/ranker_reliability.png).

## Most important features (permutation importance, mean AUC drop on held-out folds)

| Feature | AUC drop |
|---|---|
| loc | 0.1024 |
| dynamic_risk | 0.0131 |
| kind_function | 0.0098 |
| max_dup_similarity | 0.0066 |
| kind_class | 0.0051 |

Unit size (`loc`) carries most of the signal: longer units get more review comments, which is about where reviewers look, not about whether code can go.

## Why it doesn't measure safety

- The label is "a reviewer asked to remove this unit", not "removing it keeps the program's behavior"; reviewers ask to remove code that is used (comments, try/except blocks, redundant logic), and leave unused code they never look at.
- Most units are never reviewed, so a 0 means "not asked about", not "must be kept"; the classes are not safe vs. unsafe.
- The scores are small (median 0.026, at most 0.20) and on another scale than the Reviewer's safe-to-apply score, whose batching threshold (0.6) the model never reaches; the Guard's test and probe outcomes would be the right label for safety.

The Reviewer therefore keeps its category priors as the default (`exp.ranker_path` unset).
