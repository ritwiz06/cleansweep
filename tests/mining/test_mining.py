import json

import pandas as pd

from cleansweep.llm import FakeLLM
from cleansweep.mining import build_taxonomy, find_removal_requests, mine_rules
from cleansweep.mining.comments import keyword_match


def comments():
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "path": ["a.py"] * 4,
            "body": [
                "Please remove this debug print",
                "Rename this variable",
                "This helper is unused, can we delete it?",
                "Why is this here? Looks like a leftover",
            ],
        }
    )


def test_keyword_filter():
    assert list(keyword_match(comments()).id) == [1, 3, 4]


def test_llm_check_marks_removals():
    reply = {
        "comments": [
            {"id": "1", "removal": True, "category": "other", "target": "debug print"},
            {"id": "3", "removal": True, "category": "dead_code", "target": "helper"},
            {"id": "4", "removal": False, "category": None, "target": None},
        ]
    }
    out = find_removal_requests(comments(), FakeLLM({"Comments:": json.dumps(reply)}))
    assert out.set_index("id").removal.to_dict() == {1: True, 3: True, 4: False}
    assert out.set_index("id").category[3] == "dead_code"
    unchecked = find_removal_requests(comments(), None)
    assert unchecked.removal.isna().all() and len(unchecked) == 3


def test_taxonomy_picks_k_by_silhouette():
    texts = [
        "remove unused import os",
        "remove unused import sys",
        "delete debug print",
        "delete debug logging",
        "drop duplicate helper",
        "duplicate function, use the util",
        "leftover test file",
        "remove leftover script",
        "unused variable",
        "dead code here",
    ]
    tax = build_taxonomy(pd.DataFrame({"body": texts}))
    assert 6 <= len(tax) <= 9 and tax["size"].sum() == len(texts)
    assert {"top_terms", "examples", "silhouette"} <= set(tax.columns)


def test_taxonomy_drops_mentions():
    texts = [f"@agent_a+helper-1.0 remove the unused helper {i}" for i in range(10)] + [
        f"@agent_b please delete this debug file {i}" for i in range(10)
    ]
    tax = build_taxonomy(pd.DataFrame({"body": texts}), k=2)
    joined = " ".join(tax.top_terms) + " ".join(tax.examples)
    assert "agent_a" not in joined and "agent_b" not in joined and "@" not in joined


def test_rules_keep_lift_above_threshold():
    tx = pd.DataFrame(
        {
            "agent=a": [1, 1, 1, 1, 0, 0, 0, 0],
            "category=dead_code": [1, 1, 1, 0, 0, 0, 0, 0],
            "pr merged": [1, 0, 1, 0, 1, 0, 1, 0],
        }
    ).astype(bool)
    rules = mine_rules(tx, min_support=0.2)
    assert len(rules) and (rules.lift >= 1.2).all()
    assert "agent=a" in set(rules.antecedents) | set(rules.consequents)


def test_assign_clusters_matches_the_taxonomy():
    from cleansweep.mining.taxonomy import assign_clusters

    texts = [f"remove the unused helper {i}" for i in range(10)] + [
        f"please delete this debug file {i}" for i in range(10)
    ]
    requests = pd.DataFrame({"body": texts}, index=range(100, 120))
    labels = assign_clusters(requests, k=2)
    tax = build_taxonomy(requests, k=2)
    assert list(labels.index) == list(requests.index)
    assert sorted(labels.value_counts().tolist()) == sorted(tax["size"].tolist())
    assert labels.iloc[0] != labels.iloc[-1]
