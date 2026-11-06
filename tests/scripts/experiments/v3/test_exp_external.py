import importlib.util
import json
import subprocess
import time
import urllib.request
from pathlib import Path

from cleansweep.sandbox.local import open_local

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "exp_external.py"
# fake credentials, assembled at run time
KEY = "-".join(["fake", "key", "0042"])
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
    (src / "scratch.py").write_text("print(1)\n")
    (src / ".env").write_text("SOMETHING=1\n")
    ws = open_local(str(src), {"work_dir": str(tmp_path / "ws")})
    ws.container = "cs-test"
    return ws


def fake_exec(ws, calls, code=0, sleep=0.0):
    """Aider's docker exec: checks what the container gets, then asks the model once through the
    relay, edits a file and logs a test run and a proposed shell command, as Aider would."""

    def run(cmd, timeout):
        calls.append(cmd)
        env = dict(cmd[i + 1].split("=", 1) for i, x in enumerate(cmd) if x == "-e")
        assert not (Path(ws.path) / ".env").exists()  # moved aside while Aider runs
        base = env["OPENAI_API_BASE"].replace("host.docker.internal", "127.0.0.1")
        request = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps({"model": f"openai/{MODEL}"}).encode(),
            headers={"Authorization": f"Bearer {env['OPENAI_API_KEY']}"},
        )
        urllib.request.urlopen(request, timeout=10).read()
        io = Path(ws.path) / ".git" / "cs_aider"
        assert (io / "instruction.md").read_text().startswith("Clean up leftover slop")
        assert json.loads((io / "model_metadata.json").read_text())["openai/model_a"]
        rows = [
            {"kind": "test", "failed": False},
            {"kind": "shell", "commands": "rm scratch.py\nrm -rf /tmp/elsewhere"},
        ]
        (io / "log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (io / "chat_history.md").write_text("> aider\n> Run shell command? [Yes]: n\n")
        (Path(ws.path) / "pkg" / "a.py").write_text("VALUE = 1\n")
        (Path(ws.path) / ".aider.tags.cache.v4").mkdir()
        time.sleep(sleep)
        return code, f"Aider v0.86.2\nerror reply quoting {KEY}\n"

    return run


def no_docker(args, timeout=None):
    return subprocess.CompletedProcess(args, 0, "sha256:image\n", "")


def test_command_line_gives_the_container_the_relay_and_a_dummy_key():
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
    assert {"--model-metadata-file", "--no-analytics", "--no-check-update"} <= set(argv)
    cmd = ext.exec_command("cs-test", argv, 1800, "http://host.docker.internal:5555/v1")
    assert cmd[4:8] == [
        "-e",
        f"OPENAI_API_KEY={ext.DUMMY_KEY}",
        "-e",
        "OPENAI_API_BASE=" + ("http://host.docker.internal:5555/v1"),
    ]
    assert "timeout -k 30 1800 " in cmd[-1]
    settings = json.loads(ext.model_settings(MODEL))[0]
    assert settings["use_temperature"] is True and settings["edit_format"] == "diff"
    assert settings["extra_params"]["extra_body"]["chat_template_kwargs"] == {
        "enable_thinking": False
    }
    meta = json.loads(ext.model_metadata(MODEL, {"max_input_tokens": 262144, "source": "x"}))
    assert meta == {
        "openai/model_a": {"max_input_tokens": 262144, "litellm_provider": "openai", "mode": "chat"}
    }


def test_run_aider_relays_counts_deletes_and_restores(tmp_path, monkeypatch, upstream):
    ext = load()
    url, seen = upstream
    ws = workspace(tmp_path)
    calls = []
    monkeypatch.setattr(ext, "_exec", fake_exec(ws, calls))
    monkeypatch.setattr(ext, "_docker", no_docker)
    secrets = {"key": KEY, "endpoint": url}
    try:
        out = ext.run_aider(ws, tmp_path / "out", MODEL, secrets, 1800, {"max_input_tokens": 9})
        assert (out["llm_calls"], out["llm_failures"], out["test_runs"]) == (1, 0, 1)
        assert (out["prompt_tokens"], out["completion_tokens"]) == (900, 50)
        assert out["stopped"] is None and out["exit_status"] == 0
        assert out["deletions"]["executed"] == ["rm scratch.py"]
        assert [r["command"] for r in out["deletions"]["refused"]] == ["rm -rf /tmp/elsewhere"]
        assert out["moved_aside"] == [".env"] and (Path(ws.path) / ".env").exists()
        assert out["secrets_found"] == {"key": 1, "endpoint": 0}
        assert not list(Path(ws.path).glob(".aider.tags.cache*"))
        diff = ws.diff(ws.base)
        assert "deleted file mode" in diff and diff.count("diff --git") == 2
    finally:
        ws.close()
    assert seen[0][2] == f"Bearer {KEY}"  # the relay added the key
    assert KEY not in json.dumps(calls)
    for path in (tmp_path / "out").rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text()


def test_time_cap_stops_the_run_and_keeps_its_diff(tmp_path, monkeypatch, upstream):
    ext = load()
    url, _ = upstream
    ws = workspace(tmp_path)
    monkeypatch.setattr(ext, "_exec", fake_exec(ws, [], code=124, sleep=1.0))
    monkeypatch.setattr(ext, "_docker", no_docker)
    try:
        out = ext.run_aider(ws, tmp_path / "out", MODEL, {"key": KEY, "endpoint": url}, 1, {})
        assert out["stopped"] == "time cap" and out["exit_status"] == 124
        assert "-import os" in ws.diff(ws.base)
    finally:
        ws.close()


def test_run_writes_the_result_json_with_settings(tmp_path, monkeypatch, upstream):
    ext = load()
    url, _ = upstream
    ws = workspace(tmp_path)
    monkeypatch.setenv("VOYAGER_MODEL", MODEL)
    monkeypatch.setenv("VOYAGER_API_KEY", KEY)
    monkeypatch.setenv("VOYAGER_BASE_URL", url)
    monkeypatch.setattr(ext, "open_aider_workspace", lambda target, sandbox: ws)
    monkeypatch.setattr(ext, "_exec", fake_exec(ws, []))
    monkeypatch.setattr(ext, "_docker", no_docker)
    tests = {"applied": True, "new_failures": []}
    monkeypatch.setattr(ext, "final_tests", lambda target, diff, sandbox: tests)
    result = ext.run("/some/local/folder", tmp_path / "run", cap_min=0.5)
    assert result["method"] == "aider" and result["verdict"] == "everything runs"
    assert (result["llm_calls"], result["prompt_tokens"], result["test_runs"]) == (1, 900, 1)
    assert result["aider_version"] == "0.86.2" and result["image"] == "cs-aider:0.86.2"
    assert result["time_cap_s"] == 30 and "--auto-test" in result["argv"]
    assert result["context_window"]["max_input_tokens"] == 262144
    assert result["files_removed"] == 1 and result["deletions"]["executed"] == ["rm scratch.py"]
    saved = json.loads((tmp_path / "run" / "result.json").read_text())
    assert saved["model"] == "openai/model_a" and saved["stopped"] is None
    report = json.loads((tmp_path / "run" / "report.json").read_text())
    assert report["method"] == "aider"
    assert [i["action"] for i in report["plan"]["items"]] == ["apply_patch", "delete_file"]
    assert (tmp_path / "run" / "aider" / "requests.jsonl").exists()
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
