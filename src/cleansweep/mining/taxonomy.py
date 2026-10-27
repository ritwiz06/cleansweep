"""Group removal requests into kinds: TF-IDF on the comment text, then KMeans."""

from __future__ import annotations

import re

import pandas as pd

MENTION = re.compile(r"@[\w.+\-/]+")  # @-handles of bots and people say nothing about the request


def build_taxonomy(requests: pd.DataFrame, k: int | None = None) -> pd.DataFrame:
    """One row per cluster: size, top terms and two example comments. Without k, the k in
    6..15 (and below the number of requests) with the best silhouette score is used. @-mentions
    are dropped from the text first."""
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import silhouette_score

    texts = [MENTION.sub(" ", t).strip() for t in requests["body"].fillna("").astype(str)]
    if len(texts) < 3:
        return pd.DataFrame(columns=["cluster", "size", "top_terms", "examples", "silhouette"])
    vec = TfidfVectorizer(stop_words="english", min_df=1, max_features=2000, ngram_range=(1, 2))
    x = vec.fit_transform(texts)
    options = [k] if k else [c for c in range(6, 16) if c < len(texts)] or [2]
    best = None
    for c in options:
        labels = KMeans(n_clusters=c, n_init=10, random_state=0).fit_predict(x)
        score = silhouette_score(x, labels) if len(set(labels)) > 1 else -1.0
        if best is None or score > best[0]:
            best = (score, c, labels)
    score, c, labels = best
    model = KMeans(n_clusters=c, n_init=10, random_state=0).fit(x)
    terms = vec.get_feature_names_out()
    rows = []
    for cluster in range(c):
        members = [t for t, lab in zip(texts, labels, strict=True) if lab == cluster]
        top = model.cluster_centers_[cluster].argsort()[::-1][:6]
        rows.append(
            {
                "cluster": cluster,
                "size": len(members),
                "top_terms": ", ".join(terms[i] for i in top),
                "examples": " || ".join(m[:120].replace("\n", " ") for m in members[:2]),
                "silhouette": round(float(score), 3),
            }
        )
    return pd.DataFrame(rows).sort_values("size", ascending=False).reset_index(drop=True)
