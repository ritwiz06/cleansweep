from __future__ import annotations

from cleansweep.core.models import CleanupItem

from .model import PRIORS


class Ranker:
    def score(self, items: list[CleanupItem], features) -> list[CleanupItem]:
        for item in items:
            item.safe_score = PRIORS.get(item.category, 0.3)
        return items


def load_ranker(path: str | None = None) -> Ranker:
    return Ranker()
