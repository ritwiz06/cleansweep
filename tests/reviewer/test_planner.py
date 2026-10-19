from cleansweep.reviewer import build_plan


def test_plan_sorted_and_matches_expected_lanes(toy_ws, toy_expected):
    plan = build_plan(toy_ws, use_llm=False)
    assert plan.repo_id == toy_ws.repo_id
    lanes = [i.lane for i in plan.items]
    assert lanes == sorted(lanes, key=lambda lane: lane != "safe")
    by_key = {i.unit.key: i.lane for i in plan.items}
    for row in toy_expected:
        assert by_key.get(row["key"]) == row["expected_lane"], row["key"]


def test_reviewer_stub(monkeypatch, toy_repo, toy_expected):
    from cleansweep.reviewer import stub

    plan = stub.build_plan(toy_repo)
    assert len(plan.items) == len(toy_expected)
