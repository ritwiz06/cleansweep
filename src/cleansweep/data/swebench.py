"""SWE-bench Verified: tasks for the experiments, cached as a local parquet file."""

from __future__ import annotations

import json
from pathlib import Path

from cleansweep.core.config import REPO_ROOT, load_config
from cleansweep.core.models import Task


def data_path(path: str) -> Path:
    """A path from configs/data.yaml, relative to the repository root."""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def _cfg() -> dict:
    return load_config()["data"]["swebench"]


def _as_list(value) -> list[str]:
    if isinstance(value, str):
        return json.loads(value) if value.strip() else []
    return [str(v) for v in value] if value is not None else []  # parquet gives arrays


def load_rows(instance_ids: list[str] | None = None) -> list[dict]:
    """Full dataset rows (with the image name, eval script and log parser), from the cache.

    Downloads the dataset once with `datasets` when the cache file is missing.
    """
    import pandas as pd

    cfg = _cfg()
    cache = data_path(cfg["cache"])
    if not cache.exists():
        from datasets import load_dataset

        cache.parent.mkdir(parents=True, exist_ok=True)
        load_dataset(cfg["dataset"], split=cfg["split"]).to_parquet(str(cache))
    rows = pd.read_parquet(cache).to_dict("records")
    for row in rows:
        row["FAIL_TO_PASS"] = _as_list(row["FAIL_TO_PASS"])
        row["PASS_TO_PASS"] = _as_list(row["PASS_TO_PASS"])
    if instance_ids is not None:
        wanted = set(instance_ids)
        rows = [r for r in rows if r["instance_id"] in wanted]
    return rows


def to_task(row: dict) -> Task:
    return Task(
        instance_id=row["instance_id"],
        repo=row["repo"],
        base_commit=row["base_commit"],
        oracle_patch=row["patch"],
        test_patch=row["test_patch"],
        fail_to_pass=list(row["FAIL_TO_PASS"]),
        pass_to_pass=list(row["PASS_TO_PASS"]),
        version=str(row["version"]),
    )


def load_tasks(instance_ids: list[str] | None = None) -> list[Task]:
    """SWE-bench Verified tasks (500), optionally only the given instance ids."""
    return [to_task(r) for r in load_rows(instance_ids)]
