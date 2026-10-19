from __future__ import annotations

from cleansweep.core.models import CleanupItem, CodeUnit, EditResult


def apply_edit(workspace, item: CleanupItem) -> bool:
    return True


def verify(before, after, touched: list[CodeUnit], llm, cfg: dict) -> tuple[bool, dict]:
    return True, {}


class Guard:
    def __init__(self, workspace, llm, cfg: dict, repair_fn=None):
        self._results: dict[str, EditResult] = {}

    def check_batch(self, items: list[CleanupItem]) -> bool:
        for item in items:
            self._results[item.item_id] = EditResult(item.item_id, "kept")
        return True

    def results(self) -> list[EditResult]:
        return list(self._results.values())
