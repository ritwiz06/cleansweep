"""Fetch PatchDiff (repo at the pinned commit + the paper's results archive) and build the index.

    python scripts/data/data_fetch_patchdiff.py

Skips steps whose output already exists. Writes data/processed/patchdiff_index.json and the
hidden test files under data/processed/patchdiff_tests/.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import urllib.request

from cleansweep.core.config import load_config
from cleansweep.data.patchdiff import build_index
from cleansweep.data.swebench import data_path


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    cfg = load_config()["data"]["patchdiff"]
    repo = data_path(cfg["dir"])
    if not repo.exists():
        subprocess.run(["git", "clone", "-q", cfg["repo_url"], str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", cfg["commit"]], check=True)

    results = data_path(cfg["results_dir"])
    archive = results / "PatchDiff_0908.7z"
    if not archive.exists():
        results.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(cfg["results_url"], archive)
    if sha256(archive) != cfg["results_sha256"]:
        print(f"checksum mismatch for {archive}", file=sys.stderr)
        return 1
    extracted = results / "extracted"
    if not extracted.exists():
        import py7zr

        with py7zr.SevenZipFile(archive) as z:
            z.extractall(path=extracted)

    index = build_index(cfg)
    labels = [v["differs_from_oracle"] for v in index.values()]
    print(
        f"{len(index)} patches indexed: {labels.count(True)} differ, {labels.count(False)} "
        f"not shown to differ, {labels.count(None)} not tested by PatchDiff"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
