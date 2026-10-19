from __future__ import annotations

from pathlib import Path

from cleansweep.core.models import CleanupItem

# How often each kind of edit is safe, before we know anything about the unit.
PRIORS = {
    "format": 0.95,
    "unused_import": 0.9,
    "leftover_file": 0.8,
    "unused_dependency": 0.8,
    "dead_code": 0.7,
    "duplicate": 0.6,
    "wrapper": 0.6,
    "other": 0.3,
    "security": 0.0,
}


class Ranker:
    """Scores how safe each cleanup item is to apply (0 = risky, 1 = safe)."""

    def __init__(self, model=None):
        self.model = model

    def _prior(self, item: CleanupItem, row) -> float:
        score = PRIORS.get(item.category, 0.3)
        if row is not None:
            if row.get("dynamic_risk", -1) == 1:
                score *= 0.3
            if row.get("reachable_from_entry", -1) == 1 and item.category == "dead_code":
                score *= 0.5
        return round(score, 4)

    def score(self, items: list[CleanupItem], features) -> list[CleanupItem]:
        """Fill safe_score on each item and return the same list."""
        index = set(features.index) if features is not None and len(features) else set()
        for item in items:
            row = features.loc[item.unit.key] if item.unit.key in index else None
            if self.model is not None and row is not None:
                item.safe_score = float(self.model.predict_proba(row.to_frame().T)[0, 1])
            else:
                item.safe_score = self._prior(item, None if row is None else row.to_dict())
        return items


def load_ranker(path: str | None = None) -> Ranker:
    """Load a trained model, or return the prior-only ranker when path is None."""
    if path is None or not Path(path).exists():
        return Ranker()
    import joblib

    return Ranker(joblib.load(path))
