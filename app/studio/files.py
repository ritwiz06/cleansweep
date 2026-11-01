"""Safe file access for Studio: only inside the allowed roots, no secret files, always redacted."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from cleansweep.agents.secrets import Redactor, is_secret_file
from cleansweep.runlog import read_events

ROOT = Path(__file__).resolve().parents[2]
MAX_TEXT = 2_000_000
REDACT = Redactor()


class Forbidden(Exception):
    """A path outside the allowed roots, a hidden path, or a secret file."""


def default_roots(runs: str | Path) -> dict[str, Path]:
    """The folders Studio may read: its runs folder, results/ and the shipped recordings."""
    return {
        "runs": Path(runs),
        "results": ROOT / "results",
        "replay": ROOT / "demo" / "replay",
    }


def resolve(roots: dict[str, Path], root: str, rel: str = "") -> Path:
    """The real path of root/rel; Forbidden if it leaves the root or is a hidden or secret file."""
    if root not in roots:
        raise Forbidden(f"unknown root {root!r}")
    if "\x00" in rel or "\\" in rel or Path(rel).is_absolute():
        raise Forbidden(f"path not allowed: {rel!r}")
    _check_parts(Path(rel).parts if rel else (), rel)
    base = os.path.realpath(roots[root])
    path = os.path.realpath(os.path.join(base, rel))
    if path != base and not path.startswith(base + os.sep):
        raise Forbidden(f"path escapes {root}: {rel}")
    # a link inside the root may still point at a hidden or secret file there
    _check_parts(Path(os.path.relpath(path, base)).parts if path != base else (), rel)
    return Path(path)


def _check_parts(parts: tuple[str, ...], rel: str) -> None:
    if any(p == ".." or p.startswith(".") for p in parts):
        raise Forbidden(f"path not allowed: {rel}")
    if parts and is_secret_file(parts[-1]):
        raise Forbidden(f"secret file: {parts[-1]}")


def clean(value):
    """Redact every string in a JSON-like value."""
    if isinstance(value, str):
        return REDACT(value)
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [clean(v) for v in value]
    return value


def read_text(path: Path, limit: int = MAX_TEXT) -> dict:
    """A text file's redacted content, cut at `limit` characters."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"text": REDACT(text[:limit]), "truncated": len(text) > limit, "size": len(text)}


def read_json(path: Path, default=None):
    """A redacted JSON file, or `default` when it is missing or unreadable."""
    try:
        return clean(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return default


_cache: dict[str, tuple[tuple, list[dict]]] = {}
_cache_lock = threading.Lock()


def events(path: Path) -> list[dict]:
    """A run's redacted events; a finished file is read once and kept until it changes."""
    try:
        stat = path.stat()
    except OSError:
        return []
    key = (stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        hit = _cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    found = clean(read_events(path))
    with _cache_lock:
        _cache[str(path)] = (key, found)
    return found
