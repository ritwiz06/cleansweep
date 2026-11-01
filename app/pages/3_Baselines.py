"""Baselines: every method on every target set, with 95% CIs, paired tests and ablations."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.loaders import load_csv  # noqa: E402

st.set_page_config(page_title="CleanSweep · Baselines", layout="wide")
st.title("Baselines and ablations")
table = load_csv("main_table.csv")
if table is None:
    st.info(
        "No results yet. Run `python scripts/experiments/v1/exp_collect.py && "
        "python scripts/experiments/v1/exp_tables.py`."
    )
    st.stop()

st.caption(
    "Mean per target and 95% bootstrap CI (2,000 resamples). Answer keys pool the toy repo and "
    "the demo app (one target each). Hidden changed = the share of targets whose hidden checks "
    "changed. Invalid output counts one-shot replies that could not be applied; they are left "
    "out of the means."
)
sets = list(dict.fromkeys(table["target set"]))
chosen = st.sidebar.multiselect("Target sets", sets, default=sets)
st.subheader("Main table")
st.dataframe(table[table["target set"].isin(chosen)], hide_index=True, width="stretch")
figure = ROOT / "results" / "figures" / "v1" / "main_lines_removed.png"
if figure.exists():
    st.image(str(figure), caption="Lines removed per target (mean, 95% CI)")

paired = load_csv("paired_tests.csv")
if paired is not None:
    st.subheader("Paired tests against cleansweep in gatekeeper mode")
    st.caption(
        "Same targets for both methods. McNemar (exact) on hidden changes, Wilcoxon signed-rank "
        "on lines removed."
    )
    st.dataframe(paired[paired["target set"].isin(chosen)], hide_index=True, width="stretch")

ablation = load_csv("ablation.csv")
if ablation is not None:
    st.subheader("Ablations: what each part adds")
    st.dataframe(ablation[ablation["target set"].isin(chosen)], hide_index=True, width="stretch")
