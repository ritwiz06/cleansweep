import pytest

from app.studio import jobs


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "app.py").write_text("x = 1\n")
    return folder


def flags(monkeypatch, *names):
    monkeypatch.setattr(jobs, "clean_flags", lambda: frozenset(names))


def argv_for(spec, runs):
    return jobs.command({"kind": "clean", **spec}, "run", runs)[0]


def message(spec, runs):
    with pytest.raises(jobs.JobError) as err:
        jobs.command({"kind": "clean", **spec}, "run", runs)
    return str(err.value)


def test_bad_folders_get_a_readable_reason(tmp_path, project):
    runs = tmp_path / "runs"
    (tmp_path / "notes.txt").write_text("hi")
    (tmp_path / "empty").mkdir()
    assert "paste the path" in message({"target": "  "}, runs)
    assert "absolute path" in message({"target": "proj"}, runs)
    assert "no folder at" in message({"target": str(tmp_path / "missing")}, runs)
    assert "is a file" in message({"target": str(tmp_path / "notes.txt")}, runs)
    assert "no Python files" in message({"target": str(tmp_path / "empty")}, runs)
    assert "runs folder is inside" in message({"target": str(project)}, project / "runs")


def test_sandbox_is_passed_only_once_clean_takes_it(tmp_path, project, monkeypatch):
    runs = tmp_path / "runs"
    flags(monkeypatch, "--mode")
    argv = argv_for({"target": str(project), "sandbox": "none"}, runs)
    assert "--sandbox" not in argv
    monkeypatch.setattr(jobs.shutil, "which", lambda name: "/usr/bin/docker")
    assert "no Docker sandbox yet" in message({"target": str(project), "sandbox": "docker"}, runs)
    flags(monkeypatch, "--mode", "--sandbox")
    argv = argv_for({"target": str(project), "sandbox": "docker"}, runs)
    assert argv[argv.index("--sandbox") + 1] == "docker"
    argv = argv_for({"target": str(project)}, runs)
    assert argv[argv.index("--sandbox") + 1] == "auto"
    assert "sandbox must be one of" in message({"target": str(project), "sandbox": "vm"}, runs)
    monkeypatch.setattr(jobs.shutil, "which", lambda name: None)
    assert "Docker is not installed" in message({"target": str(project), "sandbox": "docker"}, runs)


def test_clean_flags_reads_this_checkouts_help():
    assert {"--mode", "--out", "--no-llm"} <= jobs.clean_flags()
