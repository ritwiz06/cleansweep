"""Group removal requests into kinds: TF-IDF on the comment text, then KMeans."""

from __future__ import annotations

import re

import pandas as pd

MENTION = re.compile(r"@[\w.+\-/]+")  # @-handles of bots and people say nothing about the request


def _fit(requests: pd.DataFrame, k: int | None):
    """TF-IDF + KMeans: (texts, labels, centers, terms, silhouette, k), or None for < 3 texts."""
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import silhouette_score

    texts = [MENTION.sub(" ", t).strip() for t in requests["body"].fillna("").astype(str)]
    if len(texts) < 3:
        return None
    vec = TfidfVectorizer(stop_words="english", min_df=1, max_features=2000, ngram_range=(1, 2))
    x = vec.fit_transform(texts)
    options = [k] if k else [c for c in range(6, 16) if c < len(texts)] or [2]
    best = None
    for c in options:
        model = KMeans(n_clusters=c, n_init=10, random_state=0).fit(x)
        labels = model.labels_
        score = silhouette_score(x, labels) if len(set(labels)) > 1 else -1.0
        if best is None or score > best[0]:
            best = (score, c, labels, model.cluster_centers_)
    score, c, labels, centers = best
    return texts, [int(v) for v in labels], centers, vec.get_feature_names_out(), score, c


def assign_clusters(requests: pd.DataFrame, k: int | None = None) -> pd.Series:
    """The taxonomy cluster of each request (same fit as build_taxonomy), on its index."""
    fit = _fit(requests, k)
    return pd.Series(fit[1] if fit else [0] * len(requests), index=requests.index, dtype=int)


def build_taxonomy(requests: pd.DataFrame, k: int | None = None) -> pd.DataFrame:
    """One row per cluster: size, top terms and two example comments. Without k, the k in
    6..15 (and below the number of requests) with the best silhouette score is used. @-mentions
    are dropped from the text first."""
    fit = _fit(requests, k)
    if fit is None:
        return pd.DataFrame(columns=["cluster", "size", "top_terms", "examples", "silhouette"])
    texts, labels, centers, terms, score, c = fit
    rows = []
    for cluster in range(c):
        members = [t for t, lab in zip(texts, labels, strict=True) if lab == cluster]
        top = centers[cluster].argsort()[::-1][:6]
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
