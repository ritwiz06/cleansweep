from __future__ import annotations

import dataclasses
import json
import types
import typing
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


def to_dict(obj: Any) -> Any:
    """Turn a dataclass (or list/dict of them) into plain JSON-ready data."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, list | tuple):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def _build(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        options = [a for a in typing.get_args(tp) if a is not type(None)]
        return _build(options[0], value) if len(options) == 1 else value
    if origin is list:
        (inner,) = typing.get_args(tp) or (Any,)
        return [_build(inner, v) for v in value]
    if origin is dict:
        args = typing.get_args(tp)
        inner = args[1] if len(args) == 2 else Any
        return {k: _build(inner, v) for k, v in value.items()}
    if dataclasses.is_dataclass(tp):
        return from_dict(tp, value)
    return value


def from_dict(cls: type[T], d: dict) -> T:
    """Rebuild a dataclass from to_dict output, including nested dataclasses."""
    hints = typing.get_type_hints(cls)
    names = {f.name for f in dataclasses.fields(cls)}
    kwargs = {k: _build(hints[k], v) for k, v in d.items() if k in names}
    return cls(**kwargs)


def save_json(obj: Any, path: str | Path) -> None:
    """Write a dataclass to a JSON file, creating parent folders."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(obj), indent=2), encoding="utf-8")


def load_json(cls: type[T], path: str | Path) -> T:
    """Read a dataclass back from a JSON file written by save_json."""
    return from_dict(cls, json.loads(Path(path).read_text(encoding="utf-8")))
