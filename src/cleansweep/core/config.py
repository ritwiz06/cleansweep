from __future__ import annotations

import copy
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_FILES = {
    "core": "base.yaml",
    "data": "data.yaml",
    "exp": "exp.yaml",
    "reviewer": "reviewer.yaml",
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(overrides: dict | None = None, config_dir: str | Path | None = None) -> dict:
    """Merge the four YAML files under core/data/exp/reviewer and load .env."""
    load_dotenv(REPO_ROOT / ".env")
    folder = Path(config_dir) if config_dir else REPO_ROOT / "configs"
    cfg: dict = {}
    for key, name in CONFIG_FILES.items():
        path = folder / name
        data = yaml.safe_load(path.read_text()) if path.exists() else None
        data = data or {}
        # base.yaml is written with a top-level "core:" key; the others are flat.
        cfg[key] = data.get(key, data) if key == "core" else data
    return _merge(cfg, overrides or {})
