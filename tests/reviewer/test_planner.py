from cleansweep.reviewer import build_plan


def test_plan_sorted_and_matches_expected_lanes(toy_ws, toy_expected):
    plan = build_plan(toy_ws, use_llm=False)
    assert plan.repo_id == toy_ws.repo_id
    lanes = [i.lane for i in plan.items]
    assert lanes == sorted(lanes, key=lambda lane: lane != "safe")
    by_key = {i.unit.key: i.lane for i in plan.items}
    for row in toy_expected:
        assert by_key.get(row["key"]) == row["expected_lane"], row["key"]


def test_v1_plan_does_not_apply_the_dynamic_refs_step(tmp_path):
    (tmp_path / "plugins.yaml").write_text("handler: tools.legacy\n")
    (tmp_path / "tools.py").write_text("def legacy(x):\n    return x * 2\n")
    plan = build_plan(str(tmp_path), use_llm=False)
    item = next(i for i in plan.items if i.unit.key == "tools.py::legacy")
    assert item.lane == "safe"  # v1 unchanged (R15); the agent team's Auditor moves it


def test_reviewer_stub(monkeypatch, toy_repo, toy_expected):
    from cleansweep.reviewer import stub

    plan = stub.build_plan(toy_repo)
    assert len(plan.items) == len(toy_expected)


def test_build_plan_uses_the_run_config(toy_ws):
    from cleansweep.core.config import load_config

    cfg = load_config()
    assert any(i.category == "dead_code" for i in build_plan(toy_ws, use_llm=False).items)
    cfg["reviewer"]["vulture_min_confidence"] = 100  # vulture's 60% hits drop out
    plan = build_plan(toy_ws, use_llm=False, cfg=cfg)
    assert not any(i.category == "dead_code" for i in plan.items)


def test_exclude_leaves_folders_alone(toy_ws):
    from cleansweep.core.config import load_config
    from cleansweep.reviewer.planner import excluded

    assert excluded("demo/app.py", ["demo/"]) and excluded("demo", ["demo/"])
    assert not excluded("demos/app.py", ["demo/"])
    cfg = load_config()
    cfg["reviewer"]["exclude"] = ["shopcart/"]
    plan = build_plan(toy_ws, use_llm=False, cfg=cfg)
    assert plan.items and not any(i.unit.path.startswith("shopcart/") for i in plan.items)
