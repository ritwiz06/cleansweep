import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

from cleansweep.sandbox.local import open_local

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "exp_external.py"
# fake credentials, assembled at run time
KEY = "-".join(["fake", "key", "0042"])
ENDPOINT = "https://" + ".".join(["llm", "example", "test"]) + "/v1"
MODEL = "model_a"


def load():
    spec = importlib.util.spec_from_file_location("exp_external", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def workspace(tmp_path):
    """A local workspace (a git repo with a base commit) standing in for a container's."""
    src = tmp_path / "proj"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "a.py").write_text("import os\n\nVALUE = 1\n")
    (src / ".env").write_text("SOMETHING=1\n")
    ws = open_local(str(src), {"work_dir": str(tmp_path / "ws")})
    ws.container = "cs-test"
    return ws


def fake_exec(ws, calls, code=0, sleep=0.0):
    """Aider's docker exec: checks what the container gets, then edits and logs as Aider would."""

    def run(cmd, env, timeout):
        calls.append(cmd)
        assert env["OPENAI_API_KEY"] == KEY and env["OPENAI_API_BASE"] == ENDPOINT
        assert not (Path(ws.path) / ".env").exists()  # moved aside while Aider runs
        io = Path(ws.path) / ".git" / "cs_aider"
        assert (io / "instruction.md").read_text().startswith("Clean up leftover slop")
        rows = [
            {"kind": "llm", "prompt_tokens": 900, "completion_tokens": 50},
            {"kind": "llm", "error": "APIConnectionError"},
            {"kind": "llm", "prompt_tokens": 1100, "completion_tokens": 70},
            {"kind": "test", "failed": False},
        ]
        (io / "log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        chat = f"> aider\nerror at {ENDPOINT} with {KEY}\n> Run shell command? [Yes]: n\n"
        (io / "chat_history.md").write_text(chat)
        (Path(ws.path) / "pkg" / "a.py").write_text("VALUE = 1\n")
        (Path(ws.path) / ".aider.tags.cache.v4").mkdir()
        time.sleep(sleep)
        return code, f"Aider v0.86.2\n{KEY}\n"

    return run


def no_docker(args, timeout=None):
    return subprocess.CompletedProcess(args, 0, "sha256:image\n", "")


def test_command_line_keeps_secrets_out_and_runs_tests_without_them():
    ext = load()
    test_cmd = ext.test_command("aidev:owner_a/repo_b@abc")
    assert test_cmd.startswith("env -u OPENAI_API_KEY -u OPENAI_API_BASE timeout 900 ")
    assert test_cmd.endswith("--continue-on-collection-errors")
    assert "--continue" not in ext.test_command("/some/local/folder")
    argv = ext.aider_argv(MODEL, test_cmd)
    for flag in ("--yes-always", "--no-auto-commits", "--auto-test", "--no-stream"):
        assert flag in argv
    assert argv[argv.index("--model") + 1] == "openai/model_a"
    assert argv[argv.index("--test-cmd") + 1] == test_cmd
    assert {"--no-analytics", "--no-check-update", "--no-gitignore"} <= set(argv)
    cmd = ext.exec_command("cs-test", argv, 1800)
    assert ["-e", "OPENAI_API_KEY", "-e", "OPENAI_API_BASE"] == cmd[4:8]
    assert "timeout -k 30 1800 " in cmd[-1]
    settings = json.loads(ext.model_settings(MODEL))[0]
    assert settings["use_temperature"] is True and settings["edit_format"] == "diff"
    assert settings["extra_params"]["extra_body"]["chat_template_kwargs"] == {
        "enable_thinking": False
    }


def test_run_aider_counts_requests_restores_files_and_redacts(tmp_path, monkeypatch):
    ext = load()
    ws = workspace(tmp_path)
    calls = []
    monkeypatch.setattr(ext, "_exec", fake_exec(ws, calls))
    monkeypatch.setattr(ext, "_docker", no_docker)
    secrets = {"key": KEY, "endpoint": ENDPOINT}
    try:
        out = ext.run_aider(ws, tmp_path / "out", MODEL, secrets, 1800)
        assert (out["llm_calls"], out["llm_failures"], out["test_runs"]) == (2, 1, 1)
        assert (out["prompt_tokens"], out["completion_tokens"]) == (2000, 120)
        assert out["stopped"] is None and out["exit_status"] == 0
        assert out["moved_aside"] == [".env"] and (Path(ws.path) / ".env").exists()
        assert out["shell_commands_declined"] == 1
        assert out["secrets_found"] == {"key": 2, "endpoint": 1}
        assert not list(Path(ws.path).glob(".aider.tags.cache*"))
        assert ws.diff(ws.base).count("diff --git") == 1  # only Aider's edit
    finally:
        ws.close()
    assert KEY not in json.dumps(calls) and ENDPOINT not in json.dumps(calls)
    for path in (tmp_path / "out").rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text() and ENDPOINT not in path.read_text()


def test_time_cap_stops_the_run_and_keeps_its_diff(tmp_path, monkeypatch):
    ext = load()
    ws = workspace(tmp_path)
    monkeypatch.setattr(ext, "_exec", fake_exec(ws, [], code=124, sleep=1.0))
    monkeypatch.setattr(ext, "_docker", no_docker)
    try:
        out = ext.run_aider(ws, tmp_path / "out", MODEL, {"key": KEY, "endpoint": ENDPOINT}, 1)
        assert out["stopped"] == "time cap" and out["exit_status"] == 124
        assert "-import os" in ws.diff(ws.base)
    finally:
        ws.close()


def test_run_writes_the_result_json_with_settings(tmp_path, monkeypatch):
    ext = load()
    ws = workspace(tmp_path)
    monkeypatch.setenv("VOYAGER_MODEL", MODEL)
    monkeypatch.setenv("VOYAGER_API_KEY", KEY)
    monkeypatch.setenv("VOYAGER_BASE_URL", ENDPOINT)
    monkeypatch.setattr(ext, "open_aider_workspace", lambda target, sandbox: ws)
    monkeypatch.setattr(ext, "_exec", fake_exec(ws, []))
    monkeypatch.setattr(ext, "_docker", no_docker)
    monkeypatch.setattr(
        ext, "final_tests", lambda target, diff, sandbox: {"applied": True, "new_failures": []}
    )
    result = ext.run("/some/local/folder", tmp_path / "run", cap_min=0.5)
    assert result["method"] == "aider" and result["verdict"] == "everything runs"
    assert (result["llm_calls"], result["prompt_tokens"], result["test_runs"]) == (2, 2000, 1)
    assert result["aider_version"] == "0.86.2" and result["image"] == "cs-aider:0.86.2"
    assert result["time_cap_s"] == 30 and "--auto-test" in result["argv"]
    assert result["stopped"] is None and result["tests_changed"] == []
    saved = json.loads((tmp_path / "run" / "result.json").read_text())
    assert saved["model"] == "openai/model_a"
    report = json.loads((tmp_path / "run" / "report.json").read_text())
    assert report["method"] == "aider" and report["results"][0]["status"] == "kept"
    assert report["plan"]["items"][0]["unit"]["path"] == "pkg/a.py"
    assert (tmp_path / "run" / "aider" / "chat_history.md").exists()
    for path in (tmp_path / "run").rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text()


def test_one_kept_edit_per_changed_file():
    ext = load()
    diff = (
        "diff --git a/pkg/a.py b/pkg/a.py\n--- a/pkg/a.py\n+++ b/pkg/a.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/scratch.py b/scratch.py\ndeleted file mode 100644\n--- a/scratch.py\n"
        "+++ /dev/null\n@@ -1 +0,0 @@\n-print(1)\n"
    )
    items, results = ext.edits(diff)
    assert [(i.unit.path, i.action) for i in items] == [
        ("pkg/a.py", "apply_patch"),
        ("scratch.py", "delete_file"),
    ]
    assert [r.status for r in results] == ["kept", "kept"]
    assert results[1].diff.startswith("diff --git a/scratch.py")


def test_inject_runs_with_the_v3_methods_in_its_own_folders(tmp_path, monkeypatch):
    ext = load()
    monkeypatch.syspath_prepend(str(ROOT / "scripts" / "experiments" / "v2"))
    import exp_inject

    for name in ("RAW", "SUMMARY", "LABELS", "resolve", "run_sweep"):
        monkeypatch.setattr(exp_inject, name, getattr(exp_inject, name))
    seen = {}

    def main(argv):
        seen.update(argv=argv, raw=exp_inject.RAW, method=exp_inject.resolve("aider"))
        seen["labels"] = exp_inject.LABELS
        return 0

    monkeypatch.setattr(exp_inject, "main", main)
    assert ext.main(["inject", "--raw", str(tmp_path), "run", "--methods", "aider"]) == 0
    assert seen["argv"] == ["run", "--methods", "aider"] and seen["raw"] == tmp_path
    assert seen["method"] == ("aider", None, {}) and "aider" in seen["labels"]
    assert exp_inject.SUMMARY == ROOT / "results" / "summary" / "v3"
    assert sys.modules["exp_inject"] is exp_inject
