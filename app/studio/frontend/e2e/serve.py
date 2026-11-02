"""Serve Studio offline for the end-to-end tests.

    python e2e/serve.py [PORT]

Results are a temporary copy of the repository's committed tables and figures plus the test
fixtures' case study and watch folder; runs go to a temporary folder.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

import uvicorn  # noqa: E402

from app.studio.server import create_app  # noqa: E402


def main(port: int) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="studio-e2e-"))
    results = tmp / "results"
    for name in ("summary", "figures", "data_summary"):
        shutil.copytree(ROOT / "results" / name, results / name)
    shutil.copytree(ROOT / "tests" / "fixtures" / "studio" / "raw", results / "raw")
    try:
        uvicorn.run(create_app(tmp / "runs", results=results), port=port, log_level="warning")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8799)
