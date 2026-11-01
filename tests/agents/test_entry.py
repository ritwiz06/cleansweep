import pytest

from cleansweep.cli import main
from cleansweep.core.models import STATS_KEYS
from cleansweep.workflow import run_sweep


def test_run_sweep_agentic_returns_a_v1_report_and_v1_events(mini, agent_cfg):
    names = []
    report = run_sweep(
        str(mini), agent_cfg, method="agentic", on_event=lambda n, p: names.append(n)
    )
    assert report.method == "agentic" and set(STATS_KEYS) <= set(report.stats)
    assert report.stats["agentic"]["verdict"] == "everything runs"
    assert names[:6] == ["open", "analyze", "baseline", "plan", "rank", "batch"]
    assert (
        names[-2:] == ["guard", "report"] and names.count("check") == names.count("check_start") > 0
    )
    run_dir = report.stats["agentic"]["run_dir"]
    assert open(f"{run_dir}/final.diff").read() == report.stats["final_diff"]  # the deliverable


def test_clean_help_lists_the_options(capsys):
    with pytest.raises(SystemExit) as stop:
        main(["clean", "--help"])
    assert stop.value.code == 0
    text = capsys.readouterr().out
    for option in ("--mode", "--budget", "--approve-plan", "--dry-run", "--out", "--no-llm"):
        assert option in text
    assert "Nothing is applied to the original folder" in " ".join(text.split())


def test_clean_errors_are_one_readable_line(mini, tmp_path, capsys):
    assert main(["clean", str(mini), "--budget", "cost=3", "--no-llm"]) == 2
    assert "unknown budget item 'cost=3'" in capsys.readouterr().err
    assert main(["clean", str(tmp_path / "missing"), "--no-llm"]) == 1
    assert "no such folder" in capsys.readouterr().err
    assert main(["clean", str(mini), "--out", str(mini / "x"), "--no-llm"]) == 1
    assert "outside the project" in capsys.readouterr().err


def test_clean_dry_run_from_the_command_line(mini, tmp_path, capsys):
    out = tmp_path / "plan"
    assert main(["clean", str(mini), "--dry-run", "--no-llm", "--quiet", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Result: nothing applied" in printed and str(out / "blueprint.md") in printed


def test_a_relative_run_folder_never_lands_in_the_workspace(mini, agent_cfg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agent_cfg["agent_out"] = "runs/r0"  # relative to where the command runs
    agent_cfg["core"]["sandbox"]["keep_workspace"] = True
    report = run_sweep(str(mini), agent_cfg, method="agentic")
    assert report.stats["agentic"]["run_dir"] == str(tmp_path / "runs" / "r0")
