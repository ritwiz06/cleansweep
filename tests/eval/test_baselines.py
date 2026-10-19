from cleansweep.eval import one_shot_llm, run_hidden_checks, tools_only
from cleansweep.llm import FakeLLM


def test_tools_only_breaks_the_getattr_trap(toy_repo, cfg):
    report = tools_only(toy_repo, cfg)
    deleted = {
        i.unit.name
        for i, r in zip(report.plan.items, report.results, strict=True)
        if r.status == "kept"
    }
    assert "cmd_export" in deleted
    hidden = run_hidden_checks(toy_repo, report.stats["final_diff"], cfg)
    assert hidden["behavior_changed"] is True
    assert hidden["visible_new_failures"]


def test_one_shot_applies_model_diff(toy_repo, cfg):
    diff = (
        "--- a/shopcart/utils.py\n+++ b/shopcart/utils.py\n@@ -22,2 +22,2 @@\n"
        ' def slugify(name):\n-    return "-".join(name.lower().split())\n'
        "+    return '-'.join(name.lower().split())\n"
    )
    cfg["llm_client"] = FakeLLM({"Clean it up": f"```diff\n{diff}```"})
    report = one_shot_llm(toy_repo, cfg, seed=0)
    assert report.results[0].status == "kept"
    assert report.stats["llm_calls"] == 1
