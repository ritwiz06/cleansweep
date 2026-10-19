from cleansweep.core.models import CleanupItem, CodeUnit
from cleansweep.scheduler import apply_with_bisection, make_batches


def items(n, category="dead_code"):
    return [
        CleanupItem(
            f"i{k}",
            CodeUnit("m.py", "function", f"f{k}"),
            category,
            "delete_unit",
            "safe",
            "r",
            safe_score=0.9,
        )
        for k in range(n)
    ]


def run(n, bad):
    return apply_with_bisection(
        make_batches(items(n), 8), lambda b: not any(i.item_id in bad for i in b)
    )


def test_bisection_isolates_bad_items():
    for bad in (set(), {"i3"}, {"i0", "i5", "i14"}):
        out = run(16, bad)
        assert set(out["rejected"]) == bad
        assert len(out["accepted"]) == 16 - len(bad)


def test_few_checks_when_bad_items_are_rare():
    assert run(16, set())["n_checks"] == 2
    assert run(16, {"i3"})["n_checks"] < 16


def test_tiers_and_dynamic_items():
    fmt = items(2, "format")
    dup = items(1, "duplicate")
    dyn = items(1)
    dyn[0].evidence = ["may be used dynamically"]
    batches = make_batches(dup + dyn + fmt, 8)
    assert batches[0] == fmt
    assert [dyn[0]] in batches
