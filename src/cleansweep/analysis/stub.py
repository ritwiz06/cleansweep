"""Fixed-data versions of the analysis functions, for when the real ones are broken."""

from __future__ import annotations

import pandas as pd

from cleansweep.core.models import FEATURE_COLUMNS, CodeUnit, CommitEvent


class CodeGraph:
    def __init__(self, repo_dir: str = ""):
        self.repo_dir = repo_dir

    def units(self) -> list[CodeUnit]:
        return []

    def callers(self, unit_key: str) -> list[str]:
        return []

    def callees(self, unit_key: str) -> list[str]:
        return []

    def is_reachable(self, unit_key: str) -> bool:
        return True

    def dynamic_risk(self, unit_key: str) -> bool:
        return False

    def framework_callback(self, unit_key: str) -> str | None:
        return None

    def dynamic_refs(self, unit_key: str) -> list[str]:
        return []


def build_graph(repo_dir: str) -> CodeGraph:
    return CodeGraph(repo_dir)


def find_duplicates(
    repo_dir: str, threshold: float = 0.8
) -> list[tuple[CodeUnit, CodeUnit, float]]:
    return []


def extract_features(
    repo_dir: str, graph, coverage_json: str | None = None, history: list[CommitEvent] | None = None
) -> pd.DataFrame:
    return pd.DataFrame(columns=FEATURE_COLUMNS)
