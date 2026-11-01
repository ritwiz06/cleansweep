"""Guard strength: what the tests catch, what only the differential probes catch, false alarms."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.loaders import false_alarms, guard_strength_table, load_csv  # noqa: E402

st.set_page_config(page_title="CleanSweep · Guard", layout="wide")
st.title("Guard strength")
rows = load_csv("guard_strength.csv")
if rows is None:
    st.info("No measurement yet. Run `python scripts/experiments/v1/exp_guard_strength.py`.")
    st.stop()

st.caption(
    "Mutants: one small change per function (flip a comparison, swap + and -, add 1 to an int, "
    "swap and/or, return None); caught if the Guard's verify fails. PatchDiff recall: the agent "
    "patch against the developer's fix, for patches PatchDiff says behave differently. Probe "
    "mode: direct runs the probes as a script; runner runs them inside the project's own test "
    "command (Django settings, conftest.py)."
)
table = guard_strength_table(rows)
experiments = [e for e in table.experiment.unique() if not e.startswith("false alarms")]
st.subheader("Caught by the tests vs. only by the probes")
st.dataframe(table[table.experiment.isin(experiments)], hide_index=True, width="stretch")
figure = ROOT / "results" / "figures" / "guard_strength.png"
if figure.exists():
    st.image(str(figure), caption="Share of mutants caught, by target set and probe mode")

st.subheader("False alarms")
st.caption(
    "verify on two identical copies, probing up to 10 touched functions although nothing "
    "changed: any rejection is a false alarm."
)
st.dataframe(false_alarms(rows), hide_index=True, width="stretch")
