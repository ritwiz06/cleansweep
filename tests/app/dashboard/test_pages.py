from streamlit.testing.v1 import AppTest

from app.dashboard.live_runner import SHIPPED_DIR
from tests.conftest import FIXTURES

APP = FIXTURES.parents[1] / "app" / "dashboard"
DEMO_RUN = SHIPPED_DIR / "20261030_demo_feature_advisory_v1"


def run_page(path, timeout=60):
    at = AppTest.from_file(str(path), default_timeout=timeout).run()
    assert not at.exception, (path.name, [e.value for e in at.exception])
    return at


def test_dashboard_home_renders():
    at = run_page(APP / "dashboard.py")
    assert [m.label for m in at.metric][:2] == ["Items found", "Kept"]


def test_result_pages_render():
    for name in ("2_Scheduler.py", "3_Baselines.py", "4_Data.py", "5_Guard.py"):
        run_page(APP / "pages" / name)


def test_live_sweep_page_offers_the_shipped_recordings():
    at = run_page(APP / "pages" / "1_Live_sweep.py")
    saved = next(s for s in at.selectbox if s.label == "Saved run")
    assert DEMO_RUN.name in [str(o).rsplit("/", 1)[-1] for o in saved.options]


def test_replay_of_a_shipped_recording_works_offline():
    at = run_page(APP / "pages" / "1_Live_sweep.py")
    next(s for s in at.selectbox if s.label == "Saved run").set_value(DEMO_RUN)
    next(s for s in at.slider if s.label == "Speed").set_value(50)
    next(b for b in at.button if b.label == "Replay").click()
    at.run(timeout=120)
    assert not at.exception, [e.value for e in at.exception]
    assert any("Behavior changed: no" in s.value for s in at.success)
    assert any(m.label == "Outcome accuracy" and m.value == "7/7" for m in at.metric)
    # nothing from an earlier frame is left: checks 2 and 3 are the only probe catches
    assert not any("Waiting for the Reviewer" in c.value for c in at.caption)
    assert sum("The probes caught" in m.value for m in at.markdown) == 2
