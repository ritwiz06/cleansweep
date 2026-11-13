"""Find recorded runs (v1 sweeps, v2 cleanups, watch folders) and read their files."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from cleansweep.runlog import REPORT_KEYS

from . import files

SKIP = {"workspace", "cache", "patches", "quarantine", "node_modules", "__pycache__", "_jobs"}
MAX_DEPTH = 4
DOCS = [
    "CLEANUP_REPORT.md",
    "blueprint.md",
    "PR_DESCRIPTION.md",
    "CHANGELOG_ENTRY.md",
    "diffstat.txt",
    "final.diff",
]
ARTIFACT = re.compile(r"^art:([a-z_]+):([0-9a-f]{8})$")
TAIL_BYTES = 262_144


def find_dirs(base: Path, depth: int = MAX_DEPTH) -> list[Path]:
    """Folders under base that hold an events.jsonl or a watch_log.jsonl (not following links)."""
    found: list[Path] = []

    def walk(folder: str, left: int) -> None:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return
        names = {e.name for e in entries}
        if "events.jsonl" in names or "watch_log.jsonl" in names:
            found.append(Path(folder))
            if "watch_log.jsonl" not in names:
                return
        if left == 0:
            return
        for e in entries:
            if (
                e.is_dir(follow_symlinks=False)
                and not e.name.startswith(".")
                and e.name not in SKIP
            ):
                walk(e.path, left - 1)

    walk(str(base), depth)
    return found


def _first_line(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            return json.loads(f.readline() or "{}")
    except (OSError, ValueError):
        return {}


def _last_line(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(f.tell() - TAIL_BYTES, 0))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return {}


def kind_of(folder: Path) -> str:
    """ "watch", "v2" (agent team) or "v1" (sweep)."""
    if (folder / "watch_log.jsonl").exists():
        return "watch"
    return "v2" if _first_line(folder / "events.jsonl").get("v") == 2 else "v1"


def summary(root: str, rel: str, folder: Path) -> dict:
    """One row of the run list, from the first and last events only."""
    kind = kind_of(folder)
    log = folder / ("watch_log.jsonl" if kind == "watch" else "events.jsonl")
    first, last = _first_line(log), _last_line(log)
    row = {
        "root": root,
        "path": rel,
        "name": folder.name,
        "kind": kind,
        "mtime": log.stat().st_mtime if log.exists() else 0,
        "target": None,
        "mode": None,
        "model": None,
        "verdict": None,
        "started": None,
        "finished": False,
    }
    if kind == "v2":
        start = first.get("payload", {})
        row.update(
            target=start.get("repo_id"),
            mode=start.get("mode"),
            model=start.get("model"),
            started=first.get("ts"),
        )
        if last.get("kind") == "run_end":
            done = last["payload"].get("summary", {})
            packages = done.get("packages", {})
            row.update(
                finished=True,
                verdict=done.get("verdict"),
                outcome={
                    "kept": packages.get("kept", 0),
                    "rolled_back": packages.get("rolled_back", 0),
                    "lines_removed": done.get("lines_removed"),
                },
            )
    elif kind == "v1":
        row.update(
            target=first.get("target"),
            mode=first.get("method"),
            model=first.get("model"),
            finished=last.get("stage") == "done" or last.get("kind") == "error",
        )
        if last.get("kind") == "error":
            row["verdict"] = "error"
    return files.clean(row)


def list_runs(roots: dict[str, Path]) -> list[dict]:
    """Every run under the allowed roots, newest first."""
    rows = []
    for root, base in roots.items():
        if not base.is_dir():
            continue
        for folder in find_dirs(base):
            rows.append(summary(root, folder.relative_to(base).as_posix(), folder))
    return sorted(rows, key=lambda r: r["mtime"], reverse=True)


def _report_stats(report: dict) -> dict:
    stats = {
        k: v for k, v in report.get("stats", {}).items() if k not in ("final_diff", "llm_events")
    }
    agentic = stats.get("agentic")
    if isinstance(agentic, dict):
        stats["agentic"] = {k: v for k, v in agentic.items() if k not in ("run_dir",)}
    return stats


def report_view(report: dict) -> dict:
    """A sweep report's numbers, plan items and Guard results, as the run views show them."""
    return {
        "repo_id": report.get("repo_id"),
        "method": report.get("method"),
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "stats": _report_stats(report),
        "items": [
            {
                "item_id": i.get("item_id"),
                "unit": (i.get("unit") or {}).get("path", "")
                + (f"::{i['unit']['name']}" if (i.get("unit") or {}).get("name") else ""),
                "category": i.get("category"),
                "lane": i.get("lane"),
                "action": i.get("action"),
                "reason": i.get("reason"),
                "evidence": i.get("evidence", []),
                "safe_score": i.get("safe_score"),
            }
            for i in (report.get("plan") or {}).get("items", [])
        ],
        "results": [
            {
                "item_id": r.get("item_id"),
                "status": r.get("status"),
                "notes": (r.get("notes") or "")[:1500],
                "diff": r.get("diff") or "",
                "tests": r.get("tests"),
            }
            for r in report.get("results", [])
        ],
        "has_final_diff": bool(report.get("stats", {}).get("final_diff")),
    }


def detail(root: str, rel: str, folder: Path) -> dict:
    """A run's summary, its report's numbers and item statuses, and the files it has."""
    out = summary(root, rel, folder)
    report = files.read_json(folder / "report.json")
    out["report"] = report_view(report) if isinstance(report, dict) else None
    out["docs"] = [name for name in DOCS if (folder / name).is_file()]
    out["has_cache"] = (folder / "cache").is_dir()
    return out


def find_reports(roots: dict[str, Path]) -> list[dict]:
    """Saved sweep reports (any .json with a report's keys) under the roots, newest first."""
    rows, seen = [], set()
    for root, base in roots.items():
        for folder, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP]
            for name in names:
                path = Path(folder, name)
                if name.startswith(".") or path.suffix != ".json" or path.is_symlink():
                    continue
                real = os.path.realpath(path)
                if real in seen:
                    continue
                seen.add(real)
                try:
                    report = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not (isinstance(report, dict) and REPORT_KEYS <= set(report)):
                    continue
                row = {
                    "root": root,
                    "path": path.relative_to(base).as_posix(),
                    "repo_id": report.get("repo_id"),
                    "method": report.get("method"),
                    "started_at": report.get("started_at"),
                    "mtime": path.stat().st_mtime,
                }
                rows.append(files.clean(row))
    return sorted(rows, key=lambda r: r["mtime"], reverse=True)


def report_file(path: Path) -> dict:
    """A saved sweep report's view; FileNotFoundError when the file is not one."""
    report = files.read_json(path) if path.suffix == ".json" and path.is_file() else None
    if not (isinstance(report, dict) and REPORT_KEYS <= set(report)):
        raise FileNotFoundError(f"not a sweep report: {path.name}")
    return report_view(report)


def final_diff(folder: Path) -> str:
    """The run's whole diff: final.diff, else the report's final_diff."""
    if (folder / "final.diff").is_file():
        return files.read_text(folder / "final.diff")["text"]
    report = files.read_json(folder / "report.json") or {}
    return (report.get("stats") or {}).get("final_diff") or ""


def project_files(folder: Path) -> dict:
    """The project's files before the cleanup (path, lines), when the run saved them."""
    data = files.read_json(folder / "project_files.json")
    if isinstance(data, dict) and isinstance(data.get("files"), list):
        return {"files": data["files"], "complete": True}
    return {"files": [], "complete": False}


def artifact(folder: Path, art_id: str) -> dict:
    """A cached artifact by id (art:<kind>:<sha8>), as JSON or text."""
    m = ARTIFACT.match(art_id)
    if not m:
        raise files.Forbidden(f"not an artifact id: {art_id}")
    for suffix in ("json", "txt"):
        path = folder / "cache" / f"{m.group(1)}_{m.group(2)}.{suffix}"
        if path.is_file():
            if suffix == "json":
                return {"id": art_id, "kind": m.group(1), "json": files.read_json(path)}
            return {"id": art_id, "kind": m.group(1), **files.read_text(path)}
    raise FileNotFoundError(f"{art_id} is not in this recording")
