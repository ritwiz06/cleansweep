"""Housekeeping for the repository and the folders next to it: remove scratch that no running job
uses, archive what is finished (the rules are in docs/repo_layout.md, "Housekeeping"). A dry run
by default; --apply acts, prints the space freed and appends a line to the log.

    python scripts/tools/housekeeping.py
    python scripts/tools/housekeeping.py --apply

Only the repository's parent folder and the temp folder's CleanSweep scratch are touched.
Archiving copies into ../cleansweep-archive/, checks each copy, adds it to SHA256SUMS, runs the
archive's tools/verify_archive.py, and only then removes the originals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cleansweep.sandbox.cleanup import TEMP_PREFIXES  # noqa: E402

PREFIXES = (*TEMP_PREFIXES, "studio-e2e-")
CACHES = {"__pycache__", ".pytest_cache", ".ruff_cache", "test-results", "playwright-report"}
COVERAGE = {".coverage", "htmlcov", "coverage.xml"}
NOT_WALKED = {".git", ".venv", "node_modules", "data", "results"}
KEEP_NOTES = {"portfolio_facts.md", "archive_tarball.sha256"}
HOUR = 3600


@dataclass
class Action:
    kind: str  # "remove" or "archive"
    path: Path
    reason: str
    dest: str = ""  # for "archive": the path inside the archive


def _old(path: Path, min_age_s: float) -> bool:
    try:
        return time.time() - path.lstat().st_mtime >= min_age_s
    except OSError:
        return False


def in_use() -> set[str]:
    """Working folders of live processes, folders running containers mount, and every running
    command line (as "cmd:<line>")."""
    out: set[str] = set()
    proc = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fn"], capture_output=True, text=True)
    out |= {line[1:] for line in proc.stdout.splitlines() if line.startswith("n")}
    proc = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True)
    out |= {f"cmd:{line}" for line in proc.stdout.splitlines()[1:]}
    if shutil.which("docker"):
        ids = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True).stdout.split()
        if ids:
            fmt = "{{range .Mounts}}{{.Source}}\n{{end}}"
            proc = subprocess.run(
                ["docker", "inspect", "-f", fmt, *ids], capture_output=True, text=True
            )
            out |= {line for line in proc.stdout.splitlines() if line}
    return out


def used(path: Path, busy: set[str]) -> bool:
    """A live process works in it, a running container mounts it, or a command line names it."""
    real = str(path.resolve())
    for item in busy:
        if item.startswith("cmd:"):
            words = item[4:].split()
            if real in item or path.name in {Path(w).name for w in words}:
                return True
        elif item == real or item.startswith(real + "/"):
            return True
    return False


def scratch(temp: Path, repo: Path, min_age_s: float) -> list[Action]:
    """Workspaces and temp folders of finished runs."""
    out = []
    for root in (temp / "cleansweep" / "ws", repo / ".cleansweep" / "ws"):
        for path in sorted(root.iterdir()) if root.is_dir() else []:
            if (path / ".git").is_dir() and _old(path, min_age_s):
                out.append(Action("remove", path, "workspace of a finished run"))
    for path in sorted(temp.iterdir()) if temp.is_dir() else []:
        if path.name.startswith(PREFIXES) and _old(path, min_age_s):
            out.append(Action("remove", path, "temp scratch of a finished run"))
    return out


def caches(repo: Path) -> list[Action]:
    """Caches, test and coverage output, and the frontend build (Studio rebuilds it)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(repo):
        here = Path(dirpath)
        for name in sorted(dirnames):
            if name in NOT_WALKED:
                dirnames.remove(name)
            elif name in CACHES | COVERAGE or (name == "dist" and here.name == "frontend"):
                out.append(Action("remove", here / name, "cache or build output"))
                dirnames.remove(name)
        for name in sorted(filenames):
            if name in COVERAGE or name.startswith(".coverage."):
                out.append(Action("remove", here / name, "coverage data"))
    return out


def duplicates(parent: Path, repo: Path) -> list[Action]:
    """Backups whose exact content is committed."""
    out = []
    backup = parent / "case_studies" / "backup"
    for path in sorted(backup.rglob("*")) if backup.is_dir() else []:
        if not path.is_file():
            continue
        blob = subprocess.run(
            ["git", "hash-object", str(path)], cwd=repo, capture_output=True, text=True
        ).stdout.strip()
        known = subprocess.run(["git", "cat-file", "-e", blob], cwd=repo, capture_output=True)
        if blob and known.returncode == 0:
            out.append(Action("remove", path, "backup of committed content"))
    return out


def _cited(name: str, notes_text: str, repo: Path) -> bool:
    if name in notes_text:
        return True
    proc = subprocess.run(["git", "grep", "-qF", name], cwd=repo, capture_output=True)
    return proc.returncode == 0


def finished(parent: Path, repo: Path, busy: set[str], min_age_s: float) -> list[Action]:
    """Into the archive: spoiled runs set aside, finished chains' scripts and logs, finished
    pushes' logs, .notes files nothing cites, and all but the latest UI-review set."""
    out = []
    for clone in [repo, *sorted(parent.glob("cleansweep-runs*"))]:
        aside = clone / "results" / "raw" / "inject_superseded"
        for path in sorted(aside.glob("sleep_*")) if aside.is_dir() else []:
            if _old(path, min_age_s) and not used(path, busy):
                dest = f"raw/{clone.name}/results_raw/inject_superseded/{path.name}"
                out.append(Action("archive", path, "runs spoiled by a sleep, set aside", dest))
    studies = parent / "case_studies"
    for script in sorted(studies.glob("*.sh")) if studies.is_dir() else []:
        group = [p for p in (script, script.with_suffix(".log")) if p.exists()]
        if all(_old(p, min_age_s) for p in group) and not used(script, busy):
            out += [Action("archive", p, "finished chain", f"case_studies/{p.name}") for p in group]
    for log in sorted(studies.glob("push_*.log")) if studies.is_dir() else []:
        if _old(log, min_age_s) and "push exit" in log.read_text(errors="replace"):
            out.append(Action("archive", log, "finished push", f"case_studies/{log.name}"))
    notes = repo / ".notes"
    if notes.is_dir():
        text = " ".join(p.read_text(errors="replace") for p in notes.rglob("*.md"))
        for path in sorted(p for p in notes.iterdir() if p.is_file()):
            if path.name not in KEEP_NOTES and not _cited(path.name, text, repo):
                out.append(Action("archive", path, "nothing cites it", f"notes/{path.name}"))
        sets = sorted(p for p in (notes / "ui_review").glob("*") if p.is_dir())
        out += [
            Action("archive", p, "older UI-review set", f"notes/ui_review/{p.name}")
            for p in sets[:-1]
        ]
    return out


def containers() -> list[Action]:
    """Stopped CleanSweep containers and dangling volumes; images are never touched."""
    if not shutil.which("docker"):
        return []
    ps = ["docker", "ps", "-a", "--filter", "status=exited", "--filter", "name=^cs-"]
    names = subprocess.run([*ps, "--format", "{{.Names}}"], capture_output=True, text=True)
    vols = ["docker", "volume", "ls", "-qf", "dangling=true"]
    volumes = subprocess.run(vols, capture_output=True, text=True)
    out = []
    for name in names.stdout.split():
        out.append(Action("remove", Path(f"container:{name}"), "stopped container"))
    for volume in volumes.stdout.split():
        out.append(Action("remove", Path(f"volume:{volume}"), "dangling volume"))
    return out


def plan(args: argparse.Namespace, busy: set[str]) -> list[Action]:
    parent, repo, temp = Path(args.parent), Path(args.repo), Path(args.temp)
    found = scratch(temp, repo, args.min_age_hours * HOUR) + caches(repo)
    found = [a for a in found + duplicates(parent, repo) if not used(a.path, busy)]
    return found + finished(parent, repo, busy, args.archive_age_hours * HOUR) + containers()


def inside(path: Path, parent: Path, temp: Path) -> bool:
    """Within the CleanSweep folders: the parent folder, or the temp folder's CleanSweep scratch."""
    if path.parts[0].startswith(("container:", "volume:")):
        return True
    real, temp = path.resolve(), temp.resolve()
    if real.is_relative_to(parent.resolve()):
        return True
    if not real.is_relative_to(temp) or real == temp:
        return False
    top = real.relative_to(temp).parts[0]
    return top == "cleansweep" or top.startswith(PREFIXES)


def size(path: Path) -> int:
    if path.is_symlink() or not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(p.lstat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def archive(actions: list[Action], store: Path) -> list[str]:
    """Copy into the archive, check each copy, add it to SHA256SUMS and run the archive's
    verifier; return the problems (none: the originals may go)."""
    sums = store / "SHA256SUMS"
    listed = {}
    for line in sums.read_text().splitlines() if sums.exists() else []:
        digest, _, rel = line.partition("  ")
        listed[rel] = digest
    clash = [a.dest for a in actions if (store / a.dest).exists()]
    if clash:
        return [f"{dest} is already in the archive" for dest in clash]
    problems = []
    for action in actions:
        dest = store / action.dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        if action.path.is_dir():
            shutil.copytree(action.path, dest)
            pairs = [(action.path / p.relative_to(dest), p) for p in dest.rglob("*") if p.is_file()]
        else:
            shutil.copy2(action.path, dest)
            pairs = [(action.path, dest)]
        for src, copy in pairs:
            digest = _digest(copy)
            if digest != _digest(src):
                problems.append(f"{copy} differs from {src}")
            listed["./" + copy.relative_to(store).as_posix()] = digest
    sums.write_text("".join(f"{listed[rel]}  {rel}\n" for rel in sorted(listed)))
    verify = store / "tools" / "verify_archive.py"
    if verify.exists():
        proc = subprocess.run([sys.executable, str(verify)], capture_output=True, text=True)
        if proc.returncode != 0:
            problems.append(f"verify_archive.py exit {proc.returncode}: {proc.stdout[-300:]}")
    return problems


def _remove(action: Action) -> None:
    kind, _, name = str(action.path).partition(":")
    if kind == "container" and name:
        subprocess.run(["docker", "rm", name], capture_output=True)
    elif kind == "volume" and name:
        subprocess.run(["docker", "volume", "rm", name], capture_output=True)
    elif action.path.is_dir() and not action.path.is_symlink():
        shutil.rmtree(action.path, ignore_errors=True)
    else:
        action.path.unlink(missing_ok=True)


def run(args: argparse.Namespace, busy: set[str] | None = None) -> dict:
    """List (or, with --apply, carry out) one pass; returns its summary."""
    actions = plan(args, in_use() if busy is None else busy)
    for action in actions:
        if not inside(action.path, Path(args.parent), Path(args.temp)):
            raise SystemExit(f"refusing {action.path}: outside the CleanSweep folders")
        dest = f" -> {action.dest}" if action.dest else ""
        print(f"{action.kind:<8} {action.path}{dest}  ({action.reason})")
    moved = [a for a in actions if a.kind == "archive"]
    freed = sum(size(a.path) for a in actions)
    problems = archive(moved, Path(args.archive)) if args.apply and moved else []
    if problems:
        freed -= sum(size(a.path) for a in moved)
    if args.apply:
        for action in actions:
            if action.kind == "remove" or not problems:
                _remove(action)
    summary = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "applied": args.apply,
        "removed": [str(a.path) for a in actions if a.kind == "remove"],
        "archived": [f"{a.path} -> {a.dest}" for a in moved],
        "freed_mb": round(freed / 1e6, 1),
        "problems": problems,
    }
    verb = "freed" if args.apply else "would free"
    print(f"{len(actions)} actions; {verb} {summary['freed_mb']} MB")
    for problem in problems:
        print("problem:", problem)
    if args.apply:
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        with Path(args.log).open("a") as f:
            f.write(json.dumps(summary) + "\n")
    return summary


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="act; without it, only list")
    parser.add_argument("--min-age-hours", type=float, default=2, help="for scratch")
    parser.add_argument("--archive-age-hours", type=float, default=24, help="for finished work")
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--parent", default=str(ROOT.parent))
    parser.add_argument("--temp", default=tempfile.gettempdir())
    parser.add_argument("--archive", default=str(ROOT.parent / "cleansweep-archive"))
    parser.add_argument("--log", default=str(ROOT / ".notes" / "housekeeping.log"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return 1 if run(parse(argv))["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
