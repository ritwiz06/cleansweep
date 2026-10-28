"""Data: SWE-bench and PatchDiff, the tiers, and the AIDev selection and mining."""

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.loaders import DATA_SUMMARY, funnel_stages, load_csv, top_rules  # noqa: E402

BAR = "#2a78d6"

st.set_page_config(page_title="CleanSweep · Data", layout="wide")
st.title("Data")

st.header("SWE-bench Verified and PatchDiff")
counts = load_csv("swebench_patchdiff.csv", DATA_SUMMARY)
tiers = load_csv("tiers.csv", DATA_SUMMARY)
if counts is None and tiers is None:
    st.info("Run `python scripts/data_summary.py` to write the counts.")
left, right = st.columns(2)
if counts is not None:
    left.subheader("Counts")
    left.dataframe(counts, hide_index=True, width="stretch")
if tiers is not None:
    right.subheader("Tiers")
    right.caption("Differ = PatchDiff says the patch behaves differently from the developer's fix.")
    right.dataframe(tiers, hide_index=True, width="stretch")

st.header("AIDev")
funnel = load_csv("aidev_funnel.csv", DATA_SUMMARY)
if funnel is not None:
    stages, reasons = funnel_stages(funnel)
    st.subheader("Selection funnel")
    fig = go.Figure(
        go.Bar(
            x=stages["count"],
            y=stages.stage,
            orientation="h",
            marker={"color": BAR},
            text=stages["count"],
            textposition="outside",
            hovertext=stages.note.fillna(""),
        )
    )
    fig.update_layout(
        height=300,
        xaxis={"type": "log", "title": "repositories (log scale)"},
        yaxis={"autorange": "reversed"},
        margin={"t": 10, "b": 40, "l": 10, "r": 40},
    )
    st.plotly_chart(fig, width="stretch")
    notes = stages[stages.note.fillna("") != ""]
    for row in notes.itertuples():
        st.caption(f"{row.stage}: {row.note}")
    st.subheader("Why candidates were dropped")
    st.dataframe(reasons, hide_index=True, width="stretch")

taxonomy = load_csv("aidev_taxonomy.csv", DATA_SUMMARY)
if taxonomy is not None:
    st.subheader("Kinds of removal requests (taxonomy clusters)")
    st.caption("TF-IDF on the request text (without @-mentions), KMeans with k by silhouette.")
    st.dataframe(
        taxonomy[["cluster", "size", "top_terms", "examples"]], hide_index=True, width="stretch"
    )

rules = load_csv("aidev_rules.csv", DATA_SUMMARY)
if rules is not None:
    st.subheader("Top association rules (by lift)")
    st.dataframe(top_rules(rules), hide_index=True, width="stretch")

detection = load_csv("detection_by_category.csv", DATA_SUMMARY)
if detection is not None:
    st.subheader("Reviewer detection by kind of request")
    st.caption(
        "Requested units = units reviewers asked agents to remove; flagged = what the static "
        "detectors report in the same commented files. Flagged as = the detector categories "
        "that do flag requested units."
    )
    level = st.radio("Rows", ["category", "cluster"], horizontal=True)
    st.dataframe(
        detection[detection.level == level].drop(columns=["level"]),
        hide_index=True,
        width="stretch",
    )
