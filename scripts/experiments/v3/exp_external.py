"""The external baseline: an established open-source coding agent, Aider, cleans a project with
the fixed instruction (prompts/external_cleanup.md), the same model and the same OpenAI-compatible
endpoint as the agent team; its final diff is judged like any other method's.

    python scripts/experiments/v3/exp_external.py TARGET --out DIR [--cap-min 30]

TARGET is a local folder or "aidev:owner/name@sha"; the v3 runners call run_external(target, cfg,
seed) with cfg["agent_out"] set, and this command line is one run with its result files (smoke
tests): result.json, final.diff, report.json and aider/ (Aider's transcripts and logs).

Aider runs in the cs-aider image (aider/Dockerfile: the AIDev image with Aider in its own venv),
the workspace mounted at /repo and the project installed as in an AIDev container: the
instruction as its one message, auto-yes, no commits, the project's tests with auto-test. The
container has network while Aider runs (the judging, on the final diff, stays network-less); the
key stays on the host (llm_relay.Relay). Root files that would reconfigure Aider are moved aside
during the run. Auto-yes declines the shell commands Aider proposes; afterwards the plain
deletions among them run in the workspace, and files it emptied are deleted (its other way to
remove a file). A run stops at the time cap, keeping its diff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from llm_relay import RELAY_HOST, REQUEST_TIMEOUT_S, Relay, context_window  # noqa: E402
from shell_deletions import delete_emptied, run_deletions  # noqa: E402

from cleansweep.agents.protocol import REASONING_OFF  # noqa: E402
from cleansweep.analysis.graph import is_test_file  # noqa: E402
from cleansweep.core.config import load_config  # noqa: E402
from cleansweep.core.io import save_json  # noqa: E402
from cleansweep.core.models import (  # noqa: E402
    CleanupItem,
    CleanupPlan,
    CodeUnit,
    EditResult,
    SweepReport,
)
from cleansweep.eval.hidden import without_install_files  # noqa: E402
from cleansweep.sandbox import open_workspace  # noqa: E402
from cleansweep.sandbox.aidev_docker import MOUNT, AidevWorkspace, _docker, open_aidev  # noqa: E402
from cleansweep.sandbox.local import open_local  # noqa: E402

VERSION = "0.86.2"
IMAGE = f"cs-aider:{VERSION}"
PROMPT = HERE / "prompts" / "external_cleanup.md"
WRAPPER = HERE / "aider" / "run_aider.py"
RAW = ROOT / "results" / "raw" / "v3" / "external"
IO = ".git/cs_aider"  # in the workspace: Aider's inputs and logs, never part of a diff
CAP_MIN = 30
DUMMY_KEY = "cs-relay-adds-the-key"  # what the container sees; the relay adds the real one
HIDE = [".env", ".aider.conf.yml", ".aider.model.settings.yml", ".aider.model.metadata.json"]
SITE = "/opt/aider/lib/python3.11/site-packages"
MODEL_MAP = f"{SITE}/litellm/model_prices_and_context_window_backup.json"
CACHE = "/root/.aider/caches/model_prices_and_context_window.json"
LOGS = ["chat_history.md", "llm_history.txt", "input_history.txt", "log.jsonl"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model_settings(model: str) -> str:
    """Aider's settings for the model (JSON, which YAML reads): diff edits with a repo map, as
    Aider sets for the capable models it knows, temperature 0 and reasoning off, as the agents'
    requests."""
    entry = {
        "name": f"openai/{model}",
        "edit_format": "diff",
        "use_repo_map": True,
        "use_temperature": True,
        "extra_params": {"extra_body": REASONING_OFF},
    }
    return json.dumps([entry], indent=1)


def model_metadata(model: str, context: dict) -> str:
    """Aider's model metadata (JSON): the token limits, so the repo map and chat-history limits
    follow the model's context window rather than Aider's unknown-model defaults."""
    info = {k: v for k, v in context.items() if k != "source"}
    return json.dumps({f"openai/{model}": {**info, "litellm_provider": "openai", "mode": "chat"}})


def test_command(target: str) -> str:
    """The project's tests as its workspace runs them (pytest, no cache, 900 s), without the
    relay's address and dummy key in their environment."""
    extra = " --continue-on-collection-errors" if target.startswith("aidev:") else ""
    pytest = f"python -m pytest -q -p no:cacheprovider{extra}"
    return f"env -u OPENAI_API_KEY -u OPENAI_API_BASE timeout 900 {pytest}"


def aider_argv(model: str, test_cmd: str) -> list[str]:
    """Aider's command line (inside the container): one message, auto-yes, no commits, auto-test;
    no analytics, update checks or release notes; logs in the workspace's .git."""
    io = f"{MOUNT}/{IO}"
    return [
        *("/opt/aider/bin/python", f"{io}/run_aider.py"),
        *("--model", f"openai/{model}"),
        *("--model-settings-file", f"{io}/model_settings.yml"),
        *("--model-metadata-file", f"{io}/model_metadata.json"),
        *("--message-file", f"{io}/instruction.md"),
        "--yes-always",
        *("--no-auto-commits", "--no-dirty-commits"),
        *("--auto-test", "--test-cmd", test_cmd),
        *("--timeout", str(REQUEST_TIMEOUT_S), "--no-stream"),
        *("--no-analytics", "--no-check-update", "--no-show-release-notes"),
        *("--no-show-model-warnings", "--no-detect-urls", "--no-gitignore"),
        *("--no-pretty", "--no-fancy-input"),
        *("--chat-history-file", f"{io}/chat_history.md"),
        *("--input-history-file", f"{io}/input_history.txt"),
        *("--llm-history-file", f"{io}/llm_history.txt"),
    ]


def exec_command(container: str, argv: list[str], cap_s: int, relay_url: str) -> list[str]:
    """The docker exec that runs Aider against the relay with the dummy key; timeout stops it at
    the cap (TERM, then KILL 30 s later)."""
    # Aider downloads litellm's model map when its copy is a day old; a fresh copy of the
    # bundled one, and litellm's own bundled map, keep both from fetching anything
    script = f"mkdir -p {Path(CACHE).parent} && cp {MODEL_MAP} {CACHE} && "
    script += f"exec timeout -k 30 {cap_s} {shlex.join(argv)}"
    env = [f"OPENAI_API_KEY={DUMMY_KEY}", f"OPENAI_API_BASE={relay_url}"]
    env += ["LITELLM_LOCAL_MODEL_COST_MAP=True", f"CS_AIDER_LOG={MOUNT}/{IO}/log.jsonl"]
    flags = [x for name in env for x in ("-e", name)]
    return ["docker", "exec", "-w", MOUNT, *flags, container, "bash", "-c", script]


def settings(model: str, test_cmd: str, cap_s: int, context: dict) -> dict:
    """Everything that defines a run, for the result (no secret values)."""
    image_id = _docker(["image", "inspect", IMAGE, "--format", "{{.Id}}"]).stdout.strip()
    return {
        "tool": "aider",
        "aider_version": VERSION,
        "image": IMAGE,
        "image_id": image_id,
        "model": f"openai/{model}",
        "endpoint": "VOYAGER_BASE_URL through a host relay that adds the key; the container "
        f"gets http://{RELAY_HOST}:<port>/v1 and the dummy key {DUMMY_KEY!r}",
        "model_settings": json.loads(model_settings(model)),
        "context_window": context,
        "argv": aider_argv(model, test_cmd),
        "test_cmd": test_cmd,
        "time_cap_s": cap_s,
        "request_timeout_s": REQUEST_TIMEOUT_S,
        "instruction_sha256": _sha(PROMPT),
        "wrapper_sha256": _sha(WRAPPER),
        "aider_defaults": {
            "auto_lint": True,
            "max_reflections": 3,
            "retries": "Aider's own: backoff from 0.25 s, doubling, until it passes 60 s",
        },
        "shell_commands": "auto-yes declines them; afterwards the runner runs the plain "
        "deletions among them (rm, git rm with -r/-f, existing relative paths); files it "
        "left empty or whitespace-only that were not empty at the base are deleted too",
        "network": "on while Aider runs; the judging runs network-less",
    }


def open_aider_workspace(target: str, sandbox: dict) -> AidevWorkspace:
    """The target's workspace with its commands in a cs-aider container, the project installed as
    in an AIDev container (the network is off after the install)."""
    cfg = {**sandbox, "aidev_image": IMAGE}
    if target.startswith("aidev:"):
        return open_aidev(target, cfg)
    if target.startswith("swebench:"):
        raise ValueError("the external baseline runs on local folders and AIDev targets")
    local = open_local(target, cfg)
    name = re.sub(r"[^a-z0-9_.-]", "-", f"cs-aider-{Path(local.path).name}".lower())
    path = Path(local.path).rename(Path(local.path).with_name(name))  # orphan sweeps match it
    run = ["run", "-d", "--name", name, "-v", f"{path}:{MOUNT}", "-w", MOUNT, IMAGE]
    proc = _docker([*run, "sleep", "infinity"], timeout=300)
    if proc.returncode != 0:
        shutil.rmtree(path, ignore_errors=True)
        raise RuntimeError(f"could not start {IMAGE}: {proc.stderr.strip()[-300:]}")
    ws = AidevWorkspace(path, local.repo_id, cfg, name)
    if not ws.install(int(cfg.get("install_timeout_s", 600))):
        ws.close()
        raise RuntimeError(f"install failed for {target}: {ws.install_log[-300:]}")
    return ws


def redact(folder: Path, secrets: dict[str, str]) -> dict[str, int]:
    """How often each secret's value appears in the files under folder (0 is expected: an error
    reply passed through could quote one); found values are replaced by the secret's name."""
    found = dict.fromkeys(secrets, 0)
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        text = new = path.read_text(encoding="utf-8", errors="replace")
        for name, value in secrets.items():
            if value:
                found[name] += new.count(value)
                new = new.replace(value, f"[{name}]")
        if new != text:
            path.write_text(new, encoding="utf-8")
    return found


def usage(requests: list[dict], log: Path) -> dict:
    """LLM requests (answered ones, as the LLM client counts them, and failed ones) and tokens
    from the relay; Aider's test runs and proposed shell commands from the wrapper's log."""
    lines = log.read_text().splitlines() if log.exists() else []
    rows = [json.loads(line) for line in lines if line.strip()]
    tests = [r for r in rows if r["kind"] == "test"]
    ok = [r for r in requests if r.get("status") == 200]
    return {
        "llm_calls": len(ok),
        "llm_failures": len(requests) - len(ok),
        "prompt_tokens": sum(r.get("prompt_tokens") or 0 for r in ok),
        "completion_tokens": sum(r.get("completion_tokens") or 0 for r in ok),
        "requests": requests,
        "test_runs": len(tests),
        "last_test_failed": tests[-1]["failed"] if tests else None,
        "shell_commands": [r["commands"] for r in rows if r["kind"] == "shell"],
    }


def changed_tests(diff: str) -> list[str]:
    """Test files the diff touches."""
    paths = re.findall(r"^diff --git a/(\S+) b/", diff, re.M)
    return [p for p in paths if is_test_file(p)]


def edits(diff: str) -> tuple[list[CleanupItem], list[EditResult]]:
    """One kept edit per file the diff changes (as the one-shot baseline records its files), so
    the review sheets and the diff audit read Aider's changes as they read any method's."""
    items, results = [], []
    for part in re.split(r"(?m)^(?=diff --git )", diff):
        head = re.match(r"diff --git a/(\S+) b/(\S+)", part)
        if not head:
            continue
        deleted = "\ndeleted file mode" in part.split("\n@@", 1)[0]
        item = CleanupItem(
            f"aider-{len(items)}",
            CodeUnit(head.group(1) if deleted else head.group(2), "file"),
            "other",
            "delete_file" if deleted else "apply_patch",
            "safe",
            "Aider's cleanup: " + ("delete the file" if deleted else "edit"),
            [],
            ["aider"],
        )
        item.patch = part
        items.append(item)
        results.append(EditResult(item.item_id, "kept", diff=part))
    return items, results


def _exec(cmd: list[str], timeout: int) -> tuple[int, str]:
    """Run the docker exec; a host timeout (docker itself stuck) counts as the cap."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as exc:
        parts = (exc.stdout, exc.stderr)
        return 124, "".join(
            x.decode(errors="replace") if isinstance(x, bytes) else x or "" for x in parts
        )


def run_aider(
    ws: AidevWorkspace, out: Path, model: str, secrets: dict, cap_s: int, context: dict
) -> dict:
    """Run Aider once in the workspace's container, then the deletions it proposed; its logs go
    to out."""
    root, io = Path(ws.path), Path(ws.path) / IO
    io.mkdir(parents=True, exist_ok=True)
    shutil.copy(PROMPT, io / "instruction.md")
    shutil.copy(WRAPPER, io / "run_aider.py")
    (io / "model_settings.yml").write_text(model_settings(model))
    (io / "model_metadata.json").write_text(model_metadata(model, context))
    with (root / ".git" / "info" / "exclude").open("a") as f:
        f.write(".aider*\n")  # Aider's tags cache
    aside = io / "aside"
    aside.mkdir(exist_ok=True)
    hidden = [n for n in HIDE if (root / n).is_file()]
    for name in hidden:
        shutil.move(root / name, aside / name)
    argv = aider_argv(model, test_command(ws.repo_id))
    _docker(["network", "connect", "bridge", ws.container])
    start = time.time()
    with Relay(secrets["endpoint"], secrets["key"]) as relay:
        code, output = _exec(exec_command(ws.container, argv, cap_s, relay.url), cap_s + 120)
    seconds = time.time() - start
    _docker(["network", "disconnect", "bridge", ws.container])
    for name in hidden:
        shutil.move(aside / name, root / name)
    for cache in root.glob(".aider.tags.cache.v*"):
        shutil.rmtree(cache, ignore_errors=True)
    logs = out / "aider"
    logs.mkdir(parents=True, exist_ok=True)
    for name in LOGS:
        if (io / name).exists():
            shutil.copy(io / name, logs / name)
    (logs / "output.txt").write_text(output)
    (logs / "requests.jsonl").write_text("".join(json.dumps(r) + "\n" for r in relay.requests))
    counts = usage(relay.requests, logs / "log.jsonl")
    capped = code in (124, 137) and seconds >= cap_s  # 137 earlier is another kill (memory)
    return {
        "exit_status": code,
        "stopped": "time cap" if capped else None,
        "seconds": round(seconds, 1),
        "moved_aside": hidden,
        "deletions": {
            **run_deletions(counts["shell_commands"], root),
            "emptied": delete_emptied(root, ws.base),
        },
        "secrets_found": redact(logs, secrets),
        **counts,
    }


def run_external(
    target: str, cfg: dict, seed: int = 0, cap_min: float | None = None
) -> SweepReport:
    """Aider on one target, returned as run_sweep returns a method's run: one kept edit per
    changed file, the final diff and the run's numbers in stats, and stats.external (version,
    settings, exit status, requests, deletions run and refused)."""
    started, t0 = _now(), time.time()
    llm_cfg = cfg.get("core", {}).get("llm", {})
    model = os.environ.get(llm_cfg.get("model_env", "VOYAGER_MODEL"), "")
    secrets = {
        "key": os.environ.get(llm_cfg.get("api_key_env", "VOYAGER_API_KEY"), ""),
        "endpoint": os.environ.get(llm_cfg.get("base_url_env", "VOYAGER_BASE_URL"), ""),
    }
    if not (model and secrets["key"] and secrets["endpoint"]):
        raise RuntimeError("set VOYAGER_MODEL, VOYAGER_BASE_URL and VOYAGER_API_KEY in .env")
    cap_s = int(60 * float(cap_min or cfg.get("exp", {}).get("external_cap_min") or CAP_MIN))
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", target.removeprefix("aidev:"))[-60:]
    out = Path(cfg.get("agent_out") or RAW / f"{slug}-{int(t0)}")
    context = context_window(secrets["endpoint"], secrets["key"], model)
    ws = open_aider_workspace(target, cfg.get("core", {}).get("sandbox") or {})
    try:
        run = run_aider(ws, out, model, secrets, cap_s, context)
        diff = ws.diff(ws.base)
        diff_stats = ws.diff_stats(ws.base)
        repo_id = ws.repo_id
    finally:
        ws.close()
    diff_secrets = {n: diff.count(v) for n, v in secrets.items()}
    for name, value in secrets.items():
        diff = diff.replace(value, f"[{name}]")
    counted = ("llm_calls", "llm_failures", "prompt_tokens", "completion_tokens", "test_runs")
    external = {
        **settings(model, test_command(target), cap_s, context),
        **{k: v for k, v in run.items() if k not in counted},
        "secrets_in_diff": diff_secrets,
        "tests_changed": changed_tests(diff),
        "out": str(out),
    }
    items, results = edits(diff)
    stats = {
        **dict.fromkeys(["items_total", "items_safe", "items_kept"], len(items)),
        **dict.fromkeys(["items_repaired", "items_rolled_back"], 0),
        "lines_removed": diff_stats["lines_removed"],
        "files_removed": diff_stats["files_removed"],
        **{k: run[k] for k in counted},
        "wall_seconds": round(time.time() - t0, 2),
        "final_diff": diff,
        "external": external,
    }
    plan = CleanupPlan(repo_id, started, items)
    return SweepReport(repo_id, "aider", "now", seed, started, _now(), plan, results, stats)


def final_tests(target: str, diff: str, sandbox: dict) -> dict:
    """The project's tests before and after the final diff in a fresh standard workspace (the
    network-less AIDev container, or a local copy), as the other methods are judged."""
    if not diff.strip():
        return {"applied": None}
    ws = open_workspace(target, sandbox)
    try:
        before = ws.run_tests()
        if not ws.apply_patch(without_install_files(diff)):
            return {"applied": False}
        after = ws.run_tests()
    finally:
        ws.close()
    counts = ("passed", "failed", "errors", "skipped")
    return {
        "applied": True,
        "before": {k: getattr(before, k) for k in counts},
        "after": {k: getattr(after, k) for k in counts},
        "new_failures": sorted(set(after.failed_ids) - set(before.failed_ids)),
    }


def verdict(diff: str, tests: dict) -> str:
    if not diff.strip():
        return "nothing applied"
    if not tests["applied"]:
        return "the diff does not apply"
    return "tests fail" if tests["new_failures"] else "everything runs"


def run(target: str, out: Path, cap_min: float) -> dict:
    """One run with its result files in out; returns the result."""
    cfg = load_config({"reviewer": {"scope": "repo"}})
    cfg["agent_out"] = str(out)
    report = run_external(target, cfg, cap_min=cap_min)
    s = report.stats
    tests = final_tests(target, s["final_diff"], cfg["core"]["sandbox"])
    result = {
        "target": target,
        "method": "aider",
        "verdict": verdict(s["final_diff"], tests),
        "minutes": round(s["wall_seconds"] / 60, 2),
        **{k: s[k] for k in ("llm_calls", "llm_failures", "prompt_tokens", "completion_tokens")},
        **{k: s[k] for k in ("test_runs", "lines_removed", "files_removed")},
        "final_tests": tests,
        **s["external"],
    }
    (out / "result.json").write_text(json.dumps(result, indent=1) + "\n")
    (out / "final.diff").write_text(s["final_diff"])
    save_json(report, out / "report.json")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target")
    parser.add_argument("--out", required=True, help="the result folder")
    parser.add_argument("--cap-min", type=float, default=CAP_MIN, help="time cap in minutes")
    args = parser.parse_args(argv)
    result = run(args.target, Path(args.out), args.cap_min)
    keys = ("verdict", "minutes", "llm_calls", "prompt_tokens", "completion_tokens", "stopped")
    print(json.dumps({k: result[k] for k in keys}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
