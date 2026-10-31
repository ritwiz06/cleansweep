"""Lessons: every rollback writes one; later decisions must check and cite the ones that apply."""

from __future__ import annotations

import fnmatch
import json
import threading
from pathlib import Path, PurePosixPath

from cleansweep.core.models import CleanupItem

PREFIX_MIN = 2  # "on_click" -> "on_*", "_safe_round" -> "_safe_*"


def name_pattern(name: str | None) -> str | None:
    """A pattern for names like this one: the first word plus "*", or the name itself."""
    if not name:
        return None
    short = name.split(".")[-1]
    lead = "_" if short.startswith("_") else ""
    word = short.lstrip("_").split("_")[0]
    if "_" in short.lstrip("_") and len(word) >= PREFIX_MIN:
        return f"{lead}{word}_*"
    return short


def pattern_for(item: CleanupItem, framework: str | None = None) -> dict:
    """The pattern a lesson about this item matches: category, unit kind, name, folder."""
    folder = PurePosixPath(item.unit.path).parent.as_posix()
    pattern = {
        "category": item.category,
        "unit_kind": item.unit.kind,
        "file_glob": "*.py" if folder in ("", ".") else f"{folder}/*.py",
    }
    if item.unit.kind != "file" and name_pattern(item.unit.name):
        pattern["name_pattern"] = name_pattern(item.unit.name)
    if framework:
        pattern["framework"] = framework
    return pattern


def matches(pattern: dict, item: CleanupItem, framework: str | None = None) -> bool:
    """True when every field the lesson's pattern sets fits the item."""
    if pattern.get("category") not in (None, item.category):
        return False
    if pattern.get("unit_kind") not in (None, item.unit.kind):
        return False
    glob = pattern.get("file_glob")
    if glob and not fnmatch.fnmatch(item.unit.path, glob):
        return False
    name_pat = pattern.get("name_pattern")
    short = (item.unit.name or "").split(".")[-1]
    if name_pat and not fnmatch.fnmatch(short, name_pat):
        return False
    return pattern.get("framework") in (None, framework)


class LessonStore:
    """The run's lessons, optionally kept in a JSON-lines file across runs."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.lessons: list[dict] = []
        self._lock = threading.Lock()
        if self.path and self.path.exists():
            lines = self.path.read_text(encoding="utf-8").splitlines()
            self.lessons = [json.loads(line) for line in lines if line.strip()]

    def add(self, pattern: dict, reason: str, source: dict) -> dict:
        with self._lock:
            lesson = {
                "lesson_id": f"L{len(self.lessons) + 1}",
                "pattern": pattern,
                "reason": reason,
                "source": source,
            }
            self.lessons.append(lesson)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(lesson) + "\n")
        return lesson

    def matching(self, item: CleanupItem, framework: str | None = None) -> list[dict]:
        """Lessons whose pattern fits an item."""
        with self._lock:
            return [les for les in self.lessons if matches(les["pattern"], item, framework)]

    def search(self, text: str) -> list[dict]:
        """Lessons whose reason or pattern mentions a word, or whose name pattern fits it."""
        text = text.strip().lower()
        out = []
        with self._lock:
            for les in self.lessons:
                blob = (les["reason"] + " " + json.dumps(les["pattern"])).lower()
                name_pat = les["pattern"].get("name_pattern")
                if text and (
                    text in blob or (name_pat and fnmatch.fnmatch(text, name_pat.lower()))
                ):
                    out.append(les)
        return out
