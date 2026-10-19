import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_check_contracts_has_no_failures():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_contracts.py")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout
    assert "FAIL" not in proc.stdout
