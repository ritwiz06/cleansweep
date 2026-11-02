"""Per-project settings for `cleansweep clean`: the project's .cleansweep.yaml, or --config FILE."""

from __future__ import annotations

from pathlib import Path

import yaml

from .budgets import parse_budget

FILE_NAME = ".cleansweep.yaml"
KEYS = ("mode", "budget", "exclude", "test_args", "install", "model")
CHOICES = {"mode": ("safe", "thorough"), "install": ("auto", "off")}


def find(project: str | Path, path: str | Path | None = None) -> Path | None:
    """The settings file: `path` when given, else the project's .cleansweep.yaml if it has one."""
    if path:
        return Path(path).expanduser()
    found = Path(project).expanduser() / FILE_NAME
    return found if found.is_file() else None


def load(path: Path) -> dict:
    """The file's settings, checked; a ValueError names the file and the bad setting."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc.strerror}") from None
    except yaml.YAMLError:
        raise ValueError(f"{path} is not valid YAML") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: write one setting per line, e.g. mode: safe")
    return {key: _check(path, key, value) for key, value in data.items()}


def _check(path: Path, key, value):
    if key not in KEYS:
        raise ValueError(f"{path}: unknown setting {key!r}; use {', '.join(KEYS)}")
    if key == "install" and value is False:
        value = "off"  # YAML reads a bare off as false
    if key in CHOICES and value not in CHOICES[key]:
        raise ValueError(f"{path}: {key} must be {' or '.join(CHOICES[key])}, got {value!r}")
    if key in ("test_args", "model") and not isinstance(value, str):
        raise ValueError(f"{path}: {key} must be text")
    if key == "exclude" and not (
        isinstance(value, list) and all(isinstance(v, str) for v in value)
    ):
        raise ValueError(f"{path}: exclude must be a list of folders")
    if key == "budget":
        if not isinstance(value, dict):
            raise ValueError(f"{path}: budget must look like {{llm: 150, minutes: 60, tests: 80}}")
        try:
            value = parse_budget(",".join(f"{k}={v}" for k, v in value.items()))
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from None
    return value
