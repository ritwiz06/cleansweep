"""Artifact cache: large things are stored once and referenced by a content ID."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

DIGEST_CHARS = 300
SLICE_LINES = 200


class ArtifactCache:
    """Stores text or JSON under `art:<kind>:<sha8>`; the same content gives the same ID."""

    def __init__(self, root: str | Path, redact=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.redact = redact
        self._lock = threading.Lock()
        self._kinds: dict[str, str] = {}

    def put(self, kind: str, content) -> str:
        """Store content (str, dict or list) and return its ID."""
        structured = not isinstance(content, str)
        text = json.dumps(content, indent=1, default=str, sort_keys=True) if structured else content
        if self.redact is not None:
            text = self.redact(text)
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        art_id = f"art:{kind}:{sha}"
        path = self._path(art_id, structured)
        with self._lock:
            if not path.exists():
                path.write_text(text, encoding="utf-8")
            self._kinds[art_id] = "json" if structured else "txt"
        return art_id

    def _path(self, art_id: str, structured: bool | None = None) -> Path:
        _, kind, sha = art_id.split(":")
        if structured is None:
            structured = (self.root / f"{kind}_{sha}.json").exists()
        return self.root / f"{kind}_{sha}.{'json' if structured else 'txt'}"

    def exists(self, art_id: str) -> bool:
        try:
            return self._path(art_id).exists()
        except ValueError:
            return False

    def text(self, art_id: str) -> str:
        """The stored text of an artifact."""
        if not self.exists(art_id):
            raise KeyError(f"no artifact {art_id}")
        return self._path(art_id).read_text(encoding="utf-8")

    def get(self, art_id: str):
        """The artifact as stored: parsed JSON for structured content, else text."""
        path = self._path(art_id)
        if not path.exists():
            raise KeyError(f"no artifact {art_id}")
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if path.suffix == ".json" else text

    def digest(self, art_id: str, chars: int = DIGEST_CHARS) -> str:
        """A short preview for messages and prompts."""
        text = " ".join(self.text(art_id).split())
        return text if len(text) <= chars else text[: chars - 3] + "..."

    def slice(self, art_id: str, start: int = 1, end: int | None = None) -> str:
        """Lines start..end (1-based, at most SLICE_LINES) with line numbers."""
        lines = self.text(art_id).splitlines()
        start = max(1, start)
        end = min(len(lines), end or start + SLICE_LINES - 1, start + SLICE_LINES - 1)
        body = "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1))
        return f"{art_id} lines {start}-{end} of {len(lines)}\n{body}"

    def ids(self) -> list[str]:
        out = []
        for path in sorted(self.root.glob("*_*.*")):
            kind, _, sha = path.stem.rpartition("_")
            out.append(f"art:{kind}:{sha}")
        return out
