from cleansweep.reviewer import run_detectors


def test_planted_items_found(toy_repo, toy_expected):
    items = {i.unit.key: i for i in run_detectors(toy_repo)}
    planted_safe = [r for r in toy_expected if r["expected_lane"] == "safe"]
    found = [r for r in planted_safe if r["key"] in items]
    assert len(found) / len(planted_safe) >= 0.9
    for row in toy_expected:
        if row["key"] in items:
            assert items[row["key"]].category == row["category"], row["key"]
            assert items[row["key"]].lane == row["expected_lane"], row["key"]


def test_traps_and_security_not_auto_deleted(toy_repo):
    items = {i.unit.key: i for i in run_detectors(toy_repo)}
    trap = items["shopcart/commands.py::cmd_export"]
    assert trap.lane == "suggest" and any("dynamic" in e for e in trap.evidence)
    sec = items["shopcart/storage.py::load_legacy"]
    assert sec.lane == "suggest" and sec.action == "report_only"


def test_items_have_evidence_and_stable_ids(toy_repo):
    first = run_detectors(toy_repo)
    second = run_detectors(toy_repo)
    assert [i.item_id for i in first] == [i.item_id for i in second]
    assert all(i.evidence and i.reason for i in first)
