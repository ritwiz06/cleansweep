"""Copy a v2 run folder into demo/replay/ as a Studio recording.

    python scripts/tools/make_recording.py RUN_DIR NAME [--report REPORT_JSON] [--redact WORD=NEW]

Copies events.jsonl, report.json (or --report), the Markdown reports, final.diff and cache/;
never the workspace, patches or quarantine. The run folder's absolute path becomes
demo/replay/NAME, and other paths under this repository or a sibling run copy become relative.
Each --redact replaces a word in every copied file, ignoring case and keeping it (for product
names a project uses in its own code that may not be committed here); the recording's
recording.json then says so. Stops when a copied file still holds an absolute home path or a
secret-looking string.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cleansweep.agents.secrets import find_secrets  # noqa: E402

REPLAY = ROOT / "demo" / "replay"
FILES = [
    "events.jsonl",
    "report.json",
    "CLEANUP_REPORT.md",
    "PR_DESCRIPTION.md",
    "CHANGELOG_ENTRY.md",
    "blueprint.md",
    "final.diff",
]
HOME = re.compile(r"/(Users|home)/[^/\s\"'`]+/")
COUNT = {1: "one", 2: "two", 3: "three", 4: "four"}


def note(n: int) -> str:
    """What a recording with n redacted words says about them."""
    names = "product name" if n == 1 else "product names"
    return (
        f"{COUNT.get(n, n)} {names} in third-party content replaced by placeholders; "
        "nothing else changed"
    )


def _case(word: str, like: str) -> str:
    if like.isupper():
        return word.upper()
    return word.capitalize() if like[0].isupper() else word


def redact(text: str, words: dict[str, str]) -> str:
    """Each word replaced by its new word, ignoring case and keeping it."""
    for old, new in words.items():
        text = re.sub(re.escape(old), lambda m, n=new: _case(n, m.group(0)), text, flags=re.I)
    return text


def relative_paths(text: str, run_name: str, name: str) -> str:
    """The run folder's absolute path -> demo/replay/NAME; repository paths -> relative."""
    folder = rf"(?<![\w.~-])/[^\s\"'`]*/{re.escape(run_name)}(?=[/\s\"'`]|$)"
    text = re.sub(folder, f"demo/replay/{name}", text)
    return re.sub(rf"{re.escape(str(ROOT.parent))}/[^/\s\"'`]+/", "", text)


def problems(folder: Path) -> list[str]:
    out = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        text = path.read_text(errors="replace")
        if HOME.search(text):
            out.append(f"{path.relative_to(folder)}: absolute home path")
        kinds = sorted({kind for kind, _, _ in find_secrets(text)})
        if kinds:
            out.append(f"{path.relative_to(folder)}: secret-looking strings ({', '.join(kinds)})")
    return out


def make(
    run: Path,
    name: str,
    report: Path | None = None,
    words: dict[str, str] | None = None,
) -> Path:
    dest = REPLAY / name
    if dest.exists():
        raise SystemExit(f"{dest} exists")
    sources = {f: run / f for f in FILES if (run / f).exists()}
    if report:
        sources["report.json"] = report
    if run.joinpath("cache").is_dir():
        sources |= {f"cache/{p.name}": p for p in sorted((run / "cache").iterdir()) if p.is_file()}
    for rel, src in sources.items():
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        text = relative_paths(src.read_text(errors="replace"), run.name, name)
        out.write_text(redact(text, words or {}))
    found = problems(dest)
    if found:
        shutil.rmtree(dest)
        raise SystemExit("not copied:\n" + "\n".join(found))
    if words:
        meta = {"recording": name, "source": run.name, "note": note(len(words))}
        (dest / "recording.json").write_text(json.dumps(meta, indent=1) + "\n")
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", help="a v2 run folder (events.jsonl, cache/, ...)")
    parser.add_argument("name", help="the recording's folder name under demo/replay/")
    parser.add_argument("--report", help="the run's report JSON when it is not in the folder")
    parser.add_argument("--redact", nargs="*", default=[], metavar="WORD=NEW")
    args = parser.parse_args(argv)
    words = dict(pair.split("=", 1) for pair in args.redact)
    report = Path(args.report) if args.report else None
    print(make(Path(args.run).resolve(), args.name, report, words))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
