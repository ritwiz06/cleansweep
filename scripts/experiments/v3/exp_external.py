"""The external baseline: an established open-source coding agent, Aider, cleans a project with
the fixed instruction (prompts/external_cleanup.md), the same model and the same OpenAI-compatible
endpoint as the agent team; its final diff is judged like any other method's.

    python scripts/experiments/v3/exp_external.py run TARGET --out DIR [--cap-min 30]
    python scripts/experiments/v3/exp_external.py case TARGET --name NAME [--cap-min 30]
    python scripts/experiments/v3/exp_external.py inject [--raw DIR] [--summary DIR] run \\
        --repos toy --methods aider ...
    python scripts/experiments/v3/exp_external.py eval --targets toy --methods aider --out DIR

TARGET is a local folder or "aidev:owner/name@sha". Aider runs in the cs-aider image (the AIDev
containers' python:3.11 with Aider in its own venv; build it from aider/Dockerfile) with the
workspace (a git repo with a `base` commit) mounted at /repo and the project installed as in an
AIDev container. It gets the instruction as its one message, auto-yes, no commits, and the
project's test command with auto-test. Unlike the network-less AIDev containers, the container
has network while Aider runs (it needs the endpoint), so the project's tests run with network
then; the judging (hidden checks, held-out tests) runs on the final diff in the standard
network-less container. The key and endpoint go in as environment variables by name only (never
on a command line or in a file) and the test command runs without them. Root files that would let
the project reconfigure Aider (.env, .aider.conf.yml, model settings and metadata) are moved aside
during the run and put back. A run stops at the time cap; the diff so far is kept and labeled.

run: DIR gets result.json (LLM requests and tokens, minutes, exit status, Aider's version and
settings, the project's tests before and after the diff in a fresh standard workspace),
final.diff, report.json and aider/ (chat transcript, LLM history, request log, output), whose
files are scanned for the key and endpoint and redacted. case: the same as a real-project record
in results/raw/case_studies/NAME (summary.json, report.json, final.diff, diffstat.txt), which
exp_real_ablation.py's review, ui and collect read. inject, eval: exp_inject.py and exp_eval.py
with the v3 methods (methods_v3.py); inject writes to results/raw/v3/inject and
results/summary/v3 unless --raw and --summary say otherwise, so v2's tables stay as they are.
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
CASES = ROOT / "results" / "raw" / "case_studies"
IO = ".git/cs_aider"  # in the workspace: Aider's inputs and logs, never part of a diff
CAP_MIN = 30
REQUEST_TIMEOUT_S = 600  # the LLM client's timeout_s
HIDE = [".env", ".aider.conf.yml", ".aider.model.settings.yml", ".aider.model.metadata.json"]
SITE = "/opt/aider/lib/python3.11/site-packages"
MODEL_MAP = f"{SITE}/litellm/model_prices_and_context_window_backup.json"
CACHE = "/root/.aider/caches/model_prices_and_context_window.json"
LOGS = ["chat_history.md", "llm_history.txt", "input_history.txt", "log.jsonl"]
SECRETS = {"key": "VOYAGER_API_KEY", "endpoint": "VOYAGER_BASE_URL"}


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


def test_command(target: str) -> str:
    """The project's tests as its workspace runs them (pytest, no cache, 900 s), without the key
    and endpoint in their environment."""
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


def exec_command(container: str, argv: list[str], cap_s: int) -> list[str]:
    """The docker exec that runs Aider: the key and endpoint pass by name (docker copies their
    values from its own environment); timeout stops it at the cap (TERM, then KILL 30 s later)."""
    # Aider downloads litellm's model map when its copy is a day old; a fresh copy of the
    # bundled one, and litellm's own bundled map, keep both from fetching anything
    script = f"mkdir -p {Path(CACHE).parent} && cp {MODEL_MAP} {CACHE} && "
    script += f"exec timeout -k 30 {cap_s} {shlex.join(argv)}"
    env = ["-e", "OPENAI_API_KEY", "-e", "OPENAI_API_BASE"]
    env += ["-e", "LITELLM_LOCAL_MODEL_COST_MAP=True", "-e", f"CS_AIDER_LOG={MOUNT}/{IO}/log.jsonl"]
    return ["docker", "exec", "-w", MOUNT, *env, container, "bash", "-c", script]


def settings(model: str, test_cmd: str, cap_s: int) -> dict:
    """Everything that defines a run, for the result (no secret values)."""
    image_id = _docker(["image", "inspect", IMAGE, "--format", "{{.Id}}"]).stdout.strip()
    return {
        "tool": "aider",
        "aider_version": VERSION,
        "image": IMAGE,
        "image_id": image_id,
        "model": f"openai/{model}",
        "endpoint": "VOYAGER_BASE_URL, OpenAI-compatible, as the LLM client",
        "model_settings": json.loads(model_settings(model)),
        "argv": aider_argv(model, test_cmd),
        "test_cmd": test_cmd,
        "time_cap_s": cap_s,
        "request_timeout_s": REQUEST_TIMEOUT_S,
        "instruction_sha256": _sha(PROMPT),
        "wrapper_sha256": _sha(WRAPPER),
        "aider_defaults": {
            "auto_lint": True,
            "map_tokens": "1024 (no known context window)",
            "max_reflections": 3,
            "retries": "Aider's own: backoff from 0.25 s, doubling, until it passes 60 s",
            "shell_commands": "suggested ones are declined (auto-yes needs an explicit yes), so "
            "Aider deletes no file: its edit formats only edit",
        },
        "network": "on while Aider runs (the endpoint); the judging runs network-less",
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
    """Replace each secret's value in the files under folder by its name; how often each was
    found."""
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


def usage(log: Path) -> dict:
    """LLM requests (successful ones, as the LLM client counts them, and failed ones), tokens and
    Aider's test runs, from the wrapper's log."""
    lines = log.read_text().splitlines() if log.exists() else []
    rows = [json.loads(line) for line in lines if line.strip()]
    llm = [r for r in rows if r["kind"] == "llm"]
    tests = [r for r in rows if r["kind"] == "test"]
    return {
        "llm_calls": sum("error" not in r for r in llm),
        "llm_failures": sum("error" in r for r in llm),
        "prompt_tokens": sum(r.get("prompt_tokens") or 0 for r in llm),
        "completion_tokens": sum(r.get("completion_tokens") or 0 for r in llm),
        "test_runs": len(tests),
        "last_test_failed": tests[-1]["failed"] if tests else None,
        "requests": llm,
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


def _text(out: str | bytes | None) -> str:
    return out.decode(errors="replace") if isinstance(out, bytes) else out or ""


def _exec(cmd: list[str], env: dict, timeout: int) -> tuple[int, str]:
    """Run the docker exec; a host timeout (docker itself stuck) counts as the cap."""
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as exc:
        return 124, _text(exc.stdout) + _text(exc.stderr)


def _secrets(llm_cfg: dict) -> dict[str, str]:
    return {
        "key": os.environ.get(llm_cfg.get("api_key_env", SECRETS["key"]), ""),
        "endpoint": os.environ.get(llm_cfg.get("base_url_env", SECRETS["endpoint"]), ""),
    }


def run_aider(ws: AidevWorkspace, out: Path, model: str, secrets: dict, cap_s: int) -> dict:
    """Run Aider once in the workspace's container; its logs go to out (redacted)."""
    io = Path(ws.path) / IO
    io.mkdir(parents=True, exist_ok=True)
    shutil.copy(PROMPT, io / "instruction.md")
    shutil.copy(WRAPPER, io / "run_aider.py")
    (io / "model_settings.yml").write_text(model_settings(model))
    with (Path(ws.path) / ".git" / "info" / "exclude").open("a") as f:
        f.write(".aider*\n")  # Aider's tags cache
    aside = io / "aside"
    aside.mkdir(exist_ok=True)
    hidden = [n for n in HIDE if (Path(ws.path) / n).is_file()]
    for name in hidden:
        shutil.move(Path(ws.path) / name, aside / name)
    argv = aider_argv(model, test_command(ws.repo_id))
    env = {**os.environ, "OPENAI_API_KEY": secrets["key"], "OPENAI_API_BASE": secrets["endpoint"]}
    _docker(["network", "connect", "bridge", ws.container])
    start = time.time()
    code, output = _exec(exec_command(ws.container, argv, cap_s), env, cap_s + 120)
    seconds = time.time() - start
    _docker(["network", "disconnect", "bridge", ws.container])
    for name in hidden:
        shutil.move(aside / name, Path(ws.path) / name)
    for cache in Path(ws.path).glob(".aider.tags.cache.v*"):
        shutil.rmtree(cache, ignore_errors=True)
    logs = out / "aider"
    logs.mkdir(parents=True, exist_ok=True)
    for name in LOGS:
        if (io / name).exists():
            shutil.copy(io / name, logs / name)
    (logs / "output.txt").write_text(output)
    capped = code in (124, 137) and seconds >= cap_s  # 137 earlier is another kill (memory)
    chat = (logs / "chat_history.md").read_text() if (logs / "chat_history.md").exists() else ""
    return {
        "exit_status": code,
        "stopped": "time cap" if capped else None,
        "seconds": round(seconds, 1),
        "moved_aside": hidden,
        "shell_commands_declined": len(re.findall(r"^> Run shell commands?\?", chat, re.M)),
        "secrets_found": redact(logs, secrets),
        **usage(logs / "log.jsonl"),
    }


def run_external(
    target: str, cfg: dict, seed: int = 0, cap_min: float | None = None
) -> SweepReport:
    """Aider on one target, returned as run_sweep returns a method's run: one kept edit per
    changed file, the final diff and the run's numbers in stats, and stats.external (version,
    settings, exit status, requests)."""
    started, t0 = _now(), time.time()
    llm_cfg = cfg.get("core", {}).get("llm", {})
    model = os.environ.get(llm_cfg.get("model_env", "VOYAGER_MODEL"), "")
    secrets = _secrets(llm_cfg)
    if not (model and secrets["key"] and secrets["endpoint"]):
        raise RuntimeError("set VOYAGER_MODEL, VOYAGER_BASE_URL and VOYAGER_API_KEY in .env")
    cap_s = int(60 * float(cap_min or cfg.get("exp", {}).get("external_cap_min") or CAP_MIN))
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", target.removeprefix("aidev:"))[-60:]
    out = Path(cfg.get("agent_out") or RAW / f"{slug}-{int(t0)}")
    ws = open_aider_workspace(target, cfg.get("core", {}).get("sandbox") or {})
    try:
        run = run_aider(ws, out, model, secrets, cap_s)
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
        **settings(model, test_command(target), cap_s),
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
        "test_runs": run["test_runs"],
        "llm_calls": run["llm_calls"],
        "prompt_tokens": run["prompt_tokens"],
        "completion_tokens": run["completion_tokens"],
        "llm_failures": run["llm_failures"],
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


def case(target: str, name: str, cap_min: float) -> dict:
    """A real-project record as exp_case_study.py writes one (the fields collect reads)."""
    dest = CASES / name
    dest.mkdir(parents=True, exist_ok=True)
    result = run(target, dest, cap_min)
    diff = (dest / "final.diff").read_text()
    stat = subprocess.run(
        ["git", "apply", "--stat", "-"], input=diff, capture_output=True, text=True
    )
    (dest / "diffstat.txt").write_text(stat.stdout)
    summary = {
        "project": target,
        "method": "aider",
        "verdict": result["verdict"],
        "seconds": round(60 * result["minutes"], 1),
        "packages": {},
        "lines_removed": result["lines_removed"],
        "files_removed": result["files_removed"],
        "llm_requests": result["llm_calls"],
        "prompt_tokens": result["prompt_tokens"],
        "completion_tokens": result["completion_tokens"],
        "test_runs": result["test_runs"],
        "stopped": result["stopped"],
    }
    (dest / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary


def runner(name: str, argv: list[str]) -> int:
    """exp_inject.py or exp_eval.py with the v3 methods."""
    from methods_v3 import plug

    sys.path.insert(0, str(HERE.parent / "v2"))
    if name == "eval":
        import exp_eval

        plug(exp_eval)
        return exp_eval.main(argv)
    import exp_inject

    parser = argparse.ArgumentParser(prog="exp_external.py inject", allow_abbrev=False)
    parser.add_argument("--raw", default=str(ROOT / "results" / "raw" / "v3" / "inject"))
    parser.add_argument("--summary", default=str(ROOT / "results" / "summary" / "v3"))
    args, rest = parser.parse_known_args(argv)
    exp_inject.RAW, exp_inject.SUMMARY = Path(args.raw), Path(args.summary)
    plug(exp_inject)
    return exp_inject.main(rest)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("inject", "eval"):
        return runner(argv[0], argv[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["run", "case"])
    parser.add_argument("target")
    parser.add_argument("--out", help="run: the result folder")
    parser.add_argument("--name", help="case: the record's name, e.g. <project>-abl-aider")
    parser.add_argument("--cap-min", type=float, default=CAP_MIN, help="time cap in minutes")
    args = parser.parse_args(argv)
    from cleansweep.sandbox.cleanup import on_start

    on_start()
    if args.what == "case":
        if not args.name:
            parser.error("case needs --name")
        print(json.dumps(case(args.target, args.name, args.cap_min)))
        return 0
    if not args.out:
        parser.error("run needs --out")
    result = run(args.target, Path(args.out), args.cap_min)
    keys = ("verdict", "minutes", "llm_calls", "prompt_tokens", "completion_tokens", "stopped")
    print(json.dumps({k: result[k] for k in keys}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
