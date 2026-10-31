"""Where the experiment scripts find the raw reports of the runs.

The runs were made in frozen copies of this repository (../cleansweep-runs, -2 to -9). Their
results/raw folders are kept in ../cleansweep-archive/raw/<copy>/results_raw/, and the scripts
default to those folders; each script's folder flags still override them.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[2] / "cleansweep-archive" / "raw"


def archived(copy: str, folder: str) -> Path:
    """A run copy's raw report folder in the archive, e.g. ("cleansweep-runs-5", "aidev_scoped")."""
    return ARCHIVE / copy / "results_raw" / folder


def aidev_folders() -> list[Path]:
    """The AIDev grid, then its rerun folders (first folder wins per repo and method)."""
    return [
        archived("cleansweep-runs-3", "aidev_sweeps"),
        archived("cleansweep-runs-5", "aidev_scoped"),
        archived("cleansweep-runs-8", "aidev_window"),
    ]


def hidden_tests_root(folder: Path) -> Path:
    """The second-model hidden tests of the copy a run folder comes from: its .cleansweep in a
    run copy, the copy's llm_caches folder in the archive."""
    folder = Path(folder)
    if folder.parent.name == "results_raw":
        return folder.parents[3] / "llm_caches" / folder.parents[1].name / "hidden_tests"
    return folder.parents[2] / ".cleansweep" / "hidden_tests"


def check_defaults(script: str, parser: argparse.ArgumentParser, args, flags: list[str]) -> None:
    """Exit with one line naming the flag when a folder left at its default does not exist."""
    for flag in flags:
        dest = flag.lstrip("-").replace("-", "_")
        value = getattr(args, dest)
        if value != parser.get_default(dest):
            continue
        for path in value if isinstance(value, list) else [value]:
            if not Path(path).exists():
                raise SystemExit(f"{script}: {path} not found; pass {flag} FOLDER")
