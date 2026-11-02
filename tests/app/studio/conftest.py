import shutil

import pytest
from fastapi.testclient import TestClient

from app.studio.server import create_app
from tests.conftest import FIXTURES

REPLAY_RUN = "20261101_toy_clean_offline"


@pytest.fixture
def results(tmp_path):
    """A small results folder: the summary fixtures, a case study and a watch folder."""
    out = tmp_path / "results"
    shutil.copytree(FIXTURES / "results_small" / "summary", out / "summary")
    shutil.copytree(FIXTURES / "studio" / "raw", out / "raw")
    return out


@pytest.fixture
def client(tmp_path, results):
    runs = tmp_path / "runs"
    runs.mkdir()
    app = create_app(runs, dist=tmp_path / "dist", hosts=("testserver",), results=results)
    with TestClient(app) as c:
        yield c
