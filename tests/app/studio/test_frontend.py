"""The frontend's own checks (build, vitest, Playwright); they need node and `npm ci` first."""

import os
import shutil
import subprocess
import sys

import pytest

from app.studio.server import FRONTEND

pytestmark = pytest.mark.slow


def run(*args: str) -> int:
    if shutil.which("npm") is None or not (FRONTEND / "node_modules").is_dir():
        pytest.skip("needs node and `npm ci` in app/studio/frontend")
    env = {**os.environ, "PYTHON": sys.executable, "CI": "1"}
    return subprocess.run(args, cwd=FRONTEND, env=env).returncode


def test_frontend_builds():
    assert run("npm", "run", "build") == 0


def test_reducers_vitest():
    assert run("npx", "vitest", "run") == 0


def test_every_screen_end_to_end():
    assert run("npx", "playwright", "test") == 0
