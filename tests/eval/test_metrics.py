from cleansweep.core.io import load_json
from cleansweep.core.models import STATS_KEYS, SweepReport
from cleansweep.eval import summarize
from tests.conftest import FIXTURES


def test_summarize_is_flat():
    report = load_json(SweepReport, FIXTURES / "sample_report.json")
    row = summarize(report, {"available": True, "behavior_changed": False})
    assert set(STATS_KEYS) <= set(row)
    assert row["behavior_changed"] is False
    assert all(not isinstance(v, dict | list) for v in row.values())
