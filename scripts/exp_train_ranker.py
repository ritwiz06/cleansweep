"""Train the ranker on the AIDev removal labels, if there are enough of them.

    python scripts/exp_train_ranker.py

With at least 300 labeled rows covering both classes (and 3+ repositories): histogram
gradient boosting, calibrated, GroupKFold by repository; writes results/summary/ranker_cv.csv,
results/figures/ranker_reliability.png and results/models/ranker.joblib (set exp.ranker_path to
use it). Otherwise the ranker keeps its category priors and the reason is printed and saved in
results/summary/ranker_status.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from cleansweep.data import load_removal_labels
from cleansweep.ranking.train import train_ranker

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    labels = load_removal_labels()
    result = train_ranker(
        labels,
        ROOT / "results" / "models" / "ranker.joblib",
        ROOT / "results" / "summary" / "ranker_cv.csv",
        ROOT / "results" / "figures" / "ranker_reliability.png",
    )
    result["label_rows"] = len(labels)
    result["positives"] = int(labels.label.sum()) if len(labels) else 0
    (ROOT / "results" / "summary").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "summary" / "ranker_status.json").write_text(
        json.dumps(result, indent=1) + "\n"
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
