import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "results_small"


def test_reproduce_tables_rebuilds_the_fixture_tables_exactly(tmp_path):
    results = tmp_path / "results"
    shutil.copytree(FIXTURE, results)
    env = {**os.environ, "PYTHON": sys.executable}
    subprocess.run(
        ["bash", "scripts/reproduce_tables.sh", str(results)], cwd=ROOT, env=env, check=True
    )
    for path in sorted((FIXTURE / "summary" / "v1").iterdir()):
        assert (results / "summary" / "v1" / path.name).read_bytes() == path.read_bytes(), path.name
    figures = {p.name for p in (results / "figures" / "v1").glob("*.png")}
    assert figures == {
        "guard_strength.png",
        "main_lines_removed.png",
        "safety_vs_yield.png",
        "scheduler_tradeoff.png",
    }
