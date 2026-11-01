"""Scheduler replay: how much slop each sweep policy leaves over a repository's history."""

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from app.dashboard.loaders import load_csv, load_replay, policy_summary, repos_label  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402

POLICY_COLOR, NONE_COLOR = "#2a78d6", "#eb6834"

st.set_page_config(page_title="CleanSweep · Scheduler", layout="wide")
st.title("Scheduler replay")
replay, curves = load_replay()
if replay is None:
    st.info(
        "No replay yet. Run `python scripts/experiments/v1/exp_replay.py` "
        "after selecting AIDev repositories."
    )
    st.stop()

st.caption(
    "Static detectors only, measured at up to 40 commits of each repository's last 300 "
    "first-parent commits. Slop debt = open slop items summed over commits; a sweep removes all "
    "open slop. Resurrection = removed code that a later commit started using."
)
excluded = int(load_config()["data"]["aidev"].get("excluded_runnable", 0))
st.subheader(f"Policies over {repos_label(replay.repo.nunique(), excluded)} (means)")
st.dataframe(policy_summary(replay), hide_index=True, width="stretch")

tradeoff = load_csv("scheduler_tradeoff.csv")
if tradeoff is not None:
    st.subheader("Trade-off: test runs vs. slop-debt reduction")
    st.caption(
        "Per repository, reduction = 1 - slop debt / slop debt when never sweeping; means and "
        "95% bootstrap CIs across repositories."
    )
    st.dataframe(tradeoff.drop(columns=["repo_set"], errors="ignore"), hide_index=True)
    figure = ROOT / "results" / "figures" / "v1" / "scheduler_tradeoff.png"
    if figure.exists():
        st.image(str(figure), width=640)

repos = sorted(replay.repo.unique())
repo = st.sidebar.selectbox("Repository", repos)
policies = [p for p in replay.policy.unique() if p != "none"]
policy = st.sidebar.selectbox("Policy", policies)
st.subheader(repo)
st.dataframe(replay[replay.repo == repo].drop(columns=["repo"]), hide_index=True, width="stretch")

if curves is not None:
    mine = curves[curves.repo == repo]
    fig = go.Figure()
    for name, color in (("none", NONE_COLOR), (policy, POLICY_COLOR)):
        c = mine[mine.policy == name]
        label = "never sweep" if name == "none" else name
        fig.add_trace(
            go.Scatter(x=c["index"], y=c.open_slop, name=label, line={"color": color, "width": 2})
        )
        if name != "none":
            swept = c[c.swept.astype(str) == "True"]
            fig.add_trace(
                go.Scatter(
                    x=swept["index"],
                    y=swept.open_slop,
                    mode="markers",
                    name="sweep",
                    marker={"color": color, "size": 8, "symbol": "line-ns-open"},
                )
            )
    fig.update_layout(
        height=360,
        xaxis_title="commit (oldest to newest)",
        yaxis_title="open slop items",
        margin={"t": 20, "b": 40, "l": 50, "r": 10},
        legend={"orientation": "h"},
    )
    st.plotly_chart(fig, width="stretch")
