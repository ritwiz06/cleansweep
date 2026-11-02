import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "tools" / "make_recording.py"


def load():
    spec = importlib.util.spec_from_file_location("make_recording", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_folder(tmp_path, extra=""):
    run = tmp_path / "runs" / "toy__agentic__r0"
    (run / "cache").mkdir(parents=True)
    (run / "workspace").mkdir()
    event = {"kind": "run_start", "payload": {"out": str(run), "note": "Acme and ACME" + extra}}
    (run / "events.jsonl").write_text(json.dumps(event) + "\n")
    (run / "cache" / "diff_1.txt").write_text(f"see {run}/patches and results/raw/{run.name}")
    (run / "workspace" / "app.py").write_text("x = 1\n")
    return run


def test_recording_has_relative_paths_and_redacted_words(tmp_path, monkeypatch):
    tool = load()
    monkeypatch.setattr(tool, "REPLAY", tmp_path / "replay")
    dest = tool.make(run_folder(tmp_path), "toy_recording", words={"acme": "vendor"})
    event = json.loads((dest / "events.jsonl").read_text())
    assert event["payload"] == {"out": "demo/replay/toy_recording", "note": "Vendor and VENDOR"}
    diff = (dest / "cache" / "diff_1.txt").read_text()
    assert diff == "see demo/replay/toy_recording/patches and results/raw/toy__agentic__r0"
    assert not (dest / "workspace").exists()


def test_a_secret_stops_the_copy(tmp_path, monkeypatch):
    tool = load()
    monkeypatch.setattr(tool, "REPLAY", tmp_path / "replay")
    fake_key = "AKIA" + "Q" * 16
    with pytest.raises(SystemExit, match="aws_access_key"):
        tool.make(run_folder(tmp_path, extra=f" {fake_key}"), "toy_recording")
    assert not (tmp_path / "replay" / "toy_recording").exists()
