import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v1"


def load(name):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_missing_default_folder_stops_with_the_flag_to_pass(tmp_path, monkeypatch):
    collect = load("exp_collect")
    monkeypatch.setattr(sys.modules["archive_paths"], "ARCHIVE", tmp_path / "no-archive")
    with pytest.raises(SystemExit) as stop:
        collect.main([])
    message = str(stop.value)
    assert message.endswith("pass --t2 FOLDER") and "\n" not in message
    # a folder given on the command line is not checked; the next default still is
    with pytest.raises(SystemExit) as stop:
        collect.main(["--t2", str(tmp_path / "anywhere")])
    assert str(stop.value).endswith("pass --t2-oneshot FOLDER")


def test_a_script_without_folder_flags_before_names_its_new_flag(tmp_path, monkeypatch):
    callbacks = load("exp_framework_callbacks")
    monkeypatch.setattr(callbacks, "REPORTS", tmp_path / "missing")
    with pytest.raises(SystemExit) as stop:
        callbacks.main([])
    assert str(stop.value).endswith("pass --reports FOLDER")


def test_archived_run_folders_find_their_hidden_tests():
    paths = load("archive_paths")
    folder = paths.archived("cleansweep-runs-5", "aidev_scoped")
    assert folder == paths.ARCHIVE / "cleansweep-runs-5" / "results_raw" / "aidev_scoped"
    tests = paths.ARCHIVE.parent / "llm_caches" / "cleansweep-runs-5" / "hidden_tests"
    assert paths.hidden_tests_root(folder) == tests
    copy = Path("/runs/cleansweep-runs-5/results/raw/aidev_scoped")
    assert paths.hidden_tests_root(copy) == Path("/runs/cleansweep-runs-5/.cleansweep/hidden_tests")
