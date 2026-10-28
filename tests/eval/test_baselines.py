import json
from pathlib import Path

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


def test_one_shot_applies_the_files_it_returns(toy_repo, cfg):
    utils = (Path(toy_repo) / "shopcart" / "utils.py").read_text()
    reply = {
        "delete": ["debug_cart.py"],
        "files": {
            "shopcart/utils.py": utils.replace('"-".join', "'-'.join"),
            "shopcart/cart.py": (Path(toy_repo) / "shopcart" / "cart.py").read_text(),  # same
        },
    }
    cfg["llm_client"] = FakeLLM({"Clean it up": f"```json\n{json.dumps(reply)}\n```"})
    report = one_shot_llm(toy_repo, cfg, seed=0)
    assert [(i.unit.path, i.action) for i in report.plan.items] == [
        ("debug_cart.py", "delete_file"),
        ("shopcart/utils.py", "apply_patch"),
    ]
    assert all(r.status == "kept" and r.diff for r in report.results)
    assert report.stats["invalid_output"] == 0 and report.stats["files_removed"] == 1
    assert "'-'.join" in report.stats["final_diff"] and report.stats["llm_calls"] == 1


def test_one_shot_records_invalid_output(toy_repo, cfg):
    for reply, reason in [
        ("--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n", "not JSON"),
        (json.dumps({"delete": ["setup.cfg"], "files": {}}), "not shown"),
        (json.dumps({"files": {"shopcart/utils.py": 3}}), "map from path"),
    ]:
        cfg["llm_client"] = FakeLLM({"Clean it up": reply})
        report = one_shot_llm(toy_repo, cfg, seed=0)
        assert report.stats["invalid_output"] == 1
        assert report.results[0].status == "skipped"
        assert (
            report.results[0].notes.startswith("invalid_output")
            and reason in report.results[0].notes
        )
        assert report.stats["final_diff"] == ""


def test_parse_cleanup_accepts_an_empty_cleanup():
    from cleansweep.eval.baselines import parse_cleanup

    assert parse_cleanup('{"delete": [], "files": {}}', ["a.py"]) == (
        {"delete": [], "files": {}},
        "",
    )
    assert parse_cleanup('{"notes": "nothing"}', ["a.py"])[0] is None


def test_one_shot_sees_only_agent_files(agent_repo):
    from cleansweep.eval.baselines import _agent_files, _collect_code

    files = _agent_files(agent_repo)
    assert "pkg/core.py" in files and "reproduce_issue.py" in files
    assert "tests/test_core.py" not in files  # untouched by the agent patch
    code, shown = _collect_code(agent_repo, paths=files)
    assert "### pkg/core.py" in code and "### tests/test_core.py" not in code
    assert shown == files


def test_collect_code_skips_a_file_that_does_not_fit(tmp_path):
    from cleansweep.eval.baselines import _collect_code

    (tmp_path / "big.py").write_text("x = 1\n" * 2000)
    (tmp_path / "small.py").write_text("y = 2\n")
    code, shown = _collect_code(str(tmp_path), budget=1000, paths=["big.py", "small.py"])
    assert shown == ["small.py"] and "### big.py" not in code
