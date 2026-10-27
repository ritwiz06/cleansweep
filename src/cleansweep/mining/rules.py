"""Association rules over pull-request transactions (apriori)."""

from __future__ import annotations

import pandas as pd


def mine_rules(
    transactions: pd.DataFrame, min_support: float = 0.02, min_lift: float = 1.2
) -> pd.DataFrame:
    """transactions: one row per transaction, one boolean column per item. Returns rules with
    lift >= min_lift, strongest first."""
    from mlxtend.frequent_patterns import apriori, association_rules

    cols = ["antecedents", "consequents", "support", "confidence", "lift"]
    if transactions.empty:
        return pd.DataFrame(columns=cols)
    frequent = apriori(transactions.astype(bool), min_support=min_support, use_colnames=True)
    if frequent.empty or frequent["itemsets"].map(len).max() < 2:
        return pd.DataFrame(columns=cols)
    rules = association_rules(frequent, metric="lift", min_threshold=min_lift)
    rules = rules[cols].sort_values(["lift", "support"], ascending=False).reset_index(drop=True)
    for c in ("antecedents", "consequents"):
        rules[c] = rules[c].map(lambda s: ", ".join(sorted(s)))
    return rules
