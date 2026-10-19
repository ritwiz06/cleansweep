"""CleanSweep dashboard. Run with: streamlit run app/dashboard.py"""

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.loaders import find_reports, load_report, plan_table, restore_command, slop_meter  # noqa: E402

STATUS_COLORS = {
    "kept": "#2e7d32",
    "repaired": "#1565c0",
    "rolled_back": "#c62828",
    "skipped": "#757575",
}

st.set_page_config(page_title="CleanSweep", layout="wide")
st.title("CleanSweep")

reports = find_reports()
choice = st.sidebar.selectbox("Sweep report", reports, format_func=lambda p: p.name)
report = load_report(choice)
st.caption(f"{report.repo_id} · method {report.method} · seed {report.seed} · {report.started_at}")

stats = report.stats
cols = st.columns(5)
cols[0].metric("Items found", stats.get("items_total", 0))
cols[1].metric("Kept", stats.get("items_kept", 0) + stats.get("items_repaired", 0))
cols[2].metric("Rolled back", stats.get("items_rolled_back", 0))
cols[3].metric("Lines removed", stats.get("lines_removed", 0))
cols[4].metric("Test runs", stats.get("test_runs", 0))

meter = slop_meter(report)
fig = go.Figure(
    go.Bar(
        x=[meter["cleaned"], meter["open"]],
        y=["cleaned", "still open"],
        orientation="h",
        marker_color=["#2e7d32", "#9e9e9e"],
    )
)
fig.update_layout(title="Slop meter (items)", height=180, margin={"t": 40, "b": 10})
st.plotly_chart(fig, width="stretch")

table = plan_table(report)
st.subheader("Cleanup plan")
st.dataframe(table.drop(columns=["item_id"]), width="stretch", hide_index=True)

st.subheader("Guard verdicts")
items = {i.item_id: i for i in report.plan.items}
for result in report.results:
    item = items.get(result.item_id)
    if item is None or result.status == "skipped":
        continue
    color = STATUS_COLORS.get(result.status, "#757575")
    with st.expander(f"{result.status.upper()} · {item.category} · {item.unit.key}"):
        st.markdown(
            f"<span style='color:{color}'>**{result.status}**</span> — {item.reason}",
            unsafe_allow_html=True,
        )
        if result.tests:
            st.write(f"tests: {result.tests.passed} passed, {result.tests.failed} failed")
        if result.notes:
            st.text(result.notes[:1500])
        if result.diff:
            st.code(result.diff, language="diff")
        if cmd := restore_command(item.evidence, item.unit.path):
            st.code(cmd, language="bash")
