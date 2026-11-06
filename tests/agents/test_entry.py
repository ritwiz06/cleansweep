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
    options = ("--mode", "--budget", "--approve-plan", "--dry-run", "--out", "--no-llm", "--config")
    for option in options:
        assert option in text
    assert "Nothing is applied to the original folder" in " ".join(text.split())


def test_clean_errors_are_one_readable_line(mini, tmp_path, capsys):
    assert main(["clean", str(mini), "--budget", "cost=3", "--no-llm"]) == 2
    assert "unknown budget item 'cost=3'" in capsys.readouterr().err
    assert main(["clean", str(tmp_path / "missing"), "--no-llm"]) == 1
    assert "no such folder" in capsys.readouterr().err
    assert main(["clean", str(mini), "--out", str(mini / "x"), "--no-llm"]) == 1
    assert "outside the project" in capsys.readouterr().err


def test_clean_reads_the_project_settings_and_options_win(mini, tmp_path, capsys, monkeypatch):
    seen = {}

    def fake_clean(path, cfg, **kwargs):
        agents = cfg["core"]["agents"]
        seen.update(kwargs, budget=agents["budget"], install=agents["install"])
        summary = {"verdict": "nothing applied", "applied": 0, "lines_removed": 0}
        summary.update(files_removed=0, suggested=0)
        return {"summary": summary, "branch": None, "files": []}

    monkeypatch.setattr("cleansweep.agents.clean_project", fake_clean)
    (mini / ".cleansweep.yaml").write_text(
        "mode: thorough\nbudget: {llm: 40, tests: 30}\nexclude: [docs]\ninstall: off\n"
    )
    argv = ["clean", str(mini), "--no-llm", "--budget", "tests=5", "--exclude", "tests/fixtures"]
    assert main(argv) == 0
    assert seen["mode"] == "thorough" and seen["exclude"] == ["docs/", "tests/fixtures/"]
    assert seen["budget"]["llm_calls"] == 40 and seen["budget"]["test_runs"] == 5
    assert seen["install"] == "off" and seen["test_args"] is None
    assert f"Settings: {mini / '.cleansweep.yaml'}" in capsys.readouterr().out
    assert main(["clean", str(mini), "--no-llm", "--config", str(tmp_path / "none.yaml")]) == 2
    assert "cannot read" in capsys.readouterr().err


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


def test_clean_resume_and_interruptions_from_the_command_line(mini, tmp_path, capsys, monkeypatch):
    from cleansweep.agents.run import Interrupted

    assert main(["clean"]) == 2 and "--resume RUN" in capsys.readouterr().err
    assert main(["clean", str(mini), "--resume", "x"]) == 2
    assert main(["clean", "--resume", str(tmp_path / "none")]) == 1
    assert "no run to resume" in capsys.readouterr().err

    def interrupted(*args, **kwargs):
        raise Interrupted(tmp_path / "out")

    monkeypatch.setattr("cleansweep.agents.clean_project", interrupted)
    assert main(["clean", str(mini), "--no-llm"]) == 130
    assert f"cleansweep clean --resume {tmp_path / 'out'}" in capsys.readouterr().err
    seen = {}

    def resumed(ref, cfg, on_event=None, approve=None):
        seen["ref"] = ref
        summary = {"verdict": "stopped: OSError: x, nothing applied", "applied": 0}
        summary |= {"lines_removed": 0, "files_removed": 0, "suggested": 0}
        return {"summary": summary, "branch": None, "files": []}

    monkeypatch.setattr("cleansweep.agents.run.resume_project", resumed)
    assert main(["clean", "--resume", "run-1", "--quiet"]) == 1  # a stopped run is an error
    assert seen["ref"] == "run-1"
    assert "Result: stopped: OSError: x, nothing applied." in capsys.readouterr().out


def test_clean_says_which_sandbox_it_uses(mini, capsys, monkeypatch):
    seen = {}

    def fake_clean(path, cfg, **kwargs):
        seen.update(kwargs)
        summary = {"verdict": "nothing applied", "applied": 0, "lines_removed": 0}
        summary |= {"files_removed": 0, "suggested": 0}
        return {"summary": summary, "branch": None, "files": []}

    monkeypatch.setattr("cleansweep.agents.clean_project", fake_clean)
    assert main(["clean", str(mini), "--no-llm", "--sandbox", "auto"]) == 0
    assert "Sandbox: docker (not a git repository)" in capsys.readouterr().out
    assert seen["sandbox"] == "auto" and not seen["untrusted"]
    assert main(["clean", str(mini), "--untrusted"]) == 2  # the tests run with sandbox none
    assert "--untrusted needs the docker sandbox" in capsys.readouterr().err
    assert main(["clean", str(mini), "--untrusted", "--sandbox", "docker"]) == 0
    assert "Sandbox: docker (--untrusted)" in capsys.readouterr().out
