"""Serve Studio offline for the end-to-end tests.

    python e2e/serve.py [PORT] [--results FOLDER]

Results are a temporary copy of the repository's committed tables and figures plus the test
fixtures' case study and watch folder, or FOLDER as it is (the user guide's screenshots use this
repository's results/); runs go to a temporary folder.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

import uvicorn  # noqa: E402

from app.studio.server import create_app  # noqa: E402


def main(port: int, results: Path | None = None) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="studio-e2e-"))
    if results is None:
        results = tmp / "results"
        for name in ("summary", "figures", "data_summary"):
            shutil.copytree(ROOT / "results" / name, results / name)
        shutil.copytree(ROOT / "tests" / "fixtures" / "studio" / "raw", results / "raw")
    try:
        uvicorn.run(create_app(tmp / "runs", results=results), port=port, log_level="warning")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serve Studio offline for the e2e tests.")
    parser.add_argument("port", nargs="?", type=int, default=8799)
    parser.add_argument("--results", type=Path, help="serve this results folder as it is")
    args = parser.parse_args()
    main(args.port, args.results.resolve() if args.results else None)
