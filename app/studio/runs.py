"""Find recorded runs (v1 sweeps, v2 cleanups, watch folders) and read their files."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

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
        "finished": False,
    }
    if kind == "v2":
        start = first.get("payload", {})
        row.update(target=start.get("repo_id"), mode=start.get("mode"), model=start.get("model"))
        if last.get("kind") == "run_end":
            row.update(finished=True, verdict=last["payload"].get("summary", {}).get("verdict"))
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


def detail(root: str, rel: str, folder: Path) -> dict:
    """A run's summary, its report's numbers and item statuses, and the files it has."""
    out = summary(root, rel, folder)
    report = files.read_json(folder / "report.json")
    if isinstance(report, dict):
        out["report"] = {
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
    else:
        out["report"] = None
    out["docs"] = [name for name in DOCS if (folder / name).is_file()]
    out["has_cache"] = (folder / "cache").is_dir()
    return out


def final_diff(folder: Path) -> str:
    """The run's whole diff: final.diff, else the report's final_diff."""
    if (folder / "final.diff").is_file():
        return files.read_text(folder / "final.diff")["text"]
    report = files.read_json(folder / "report.json") or {}
    return (report.get("stats") or {}).get("final_diff") or ""


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
