from cleansweep.reviewer import run_detectors


def test_rewrite_patches_apply_and_tests_pass(toy_ws):
    items = [i for i in run_detectors(toy_ws.path) if i.action == "replace_with"]
    assert {i.category for i in items} == {"duplicate", "wrapper"}
    for item in items:
        assert toy_ws.apply_patch(item.patch), item.unit.key
    assert toy_ws.run_tests(None).ok


def test_duplicate_points_at_kept_copy(toy_repo):
    items = {i.unit.key: i for i in run_detectors(toy_repo)}
    dup = items["shopcart/discounts.py::_round_price"]
    assert dup.keep_target == "shopcart/utils.py::round_price"
    assert "+from shopcart.utils import round_price" in dup.patch
