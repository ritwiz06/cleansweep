"""Fixed outputs for comment mining, until the real versions land."""

from __future__ import annotations

import pandas as pd


def find_removal_requests(comments: pd.DataFrame, llm=None) -> pd.DataFrame:
    if "body" not in comments:
        return comments.iloc[0:0]
    mask = comments["body"].str.contains("unused|remove|duplicate|not needed", case=False)
    return comments[mask].copy()


def build_taxonomy(requests: pd.DataFrame, k: int | None = None) -> pd.DataFrame:
    return pd.DataFrame({"cluster": [0], "name": ["unused code"], "size": [len(requests)]})


def mine_rules(transactions: pd.DataFrame, min_support: float = 0.02) -> pd.DataFrame:
    return pd.DataFrame(columns=["antecedents", "consequents", "support", "confidence", "lift"])
