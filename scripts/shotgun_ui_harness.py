"""Snapshot shotgun's Textual screens and widgets headless; runs inside shotgun's container.

    python shotgun_ui_harness.py > snapshots.json

Every class in shotgun.tui.screens, .widgets and .components that is a Textual widget (screens
included) is mounted in a small app under App.run_test. A class that needs arguments gets a
placeholder for each required one, chosen by its annotation (the same in every run). Its
snapshot is the widget tree and the visible text of the screen. A module that no longer imports,
or a class that fails to build or mount, is recorded with the error's type and message.
"""

import asyncio
import html
import importlib
import inspect
import json
import pkgutil
import re

from textual.app import App
from textual.screen import Screen
from textual.widget import Widget

PACKAGES = ["shotgun.tui.screens", "shotgun.tui.widgets", "shotgun.tui.components"]
SIZE = (100, 32)


def _clean(text: str) -> str:
    return re.sub(r"0x[0-9a-f]+", "0x", text)[:300]


def targets() -> tuple[dict[str, type], dict[str, str]]:
    found, errors = {}, {}
    for name in PACKAGES:
        try:
            pkg = importlib.import_module(name)
        except Exception as exc:
            errors[name] = _clean(f"{type(exc).__name__}: {exc}")
            continue
        for info in pkgutil.walk_packages(pkg.__path__, f"{name}."):
            try:
                mod = importlib.import_module(info.name)
            except Exception as exc:
                errors[info.name] = _clean(f"{type(exc).__name__}: {exc}")
                continue
            for attr, obj in sorted(vars(mod).items()):
                if inspect.isclass(obj) and obj.__module__ == mod.__name__:
                    if issubclass(obj, Widget):
                        found[f"{mod.__name__}.{attr}"] = obj
    return found, errors


def _placeholder(annotation) -> object:
    text = str(annotation)
    if "None" in text:
        return None
    for kind, value in (("str", "example"), ("int", 1), ("float", 1.0), ("bool", False)):
        if re.search(rf"\b{kind}\b", text):
            return value
    if "list" in text or "Sequence" in text:
        return []
    if "dict" in text or "Mapping" in text:
        return {}
    return None


def build(cls: type) -> object:
    """cls(), or cls with a placeholder for each required argument."""
    try:
        return cls()
    except TypeError:
        pass
    kwargs = {
        p.name: _placeholder(p.annotation)
        for p in list(inspect.signature(cls.__init__).parameters.values())[1:]
        if p.default is p.empty and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    }
    return cls(**kwargs)


class Harness(App):
    def __init__(self, cls: type):
        super().__init__()
        self.cls = cls
        self.error = None

    def on_mount(self) -> None:
        try:
            obj = build(self.cls)
        except Exception as exc:
            self.error = _clean(f"build: {type(exc).__name__}: {exc}")
            return
        if isinstance(obj, Screen):
            self.push_screen(obj)
        else:
            self.mount(obj)


def _text(svg: str) -> str:
    return " ".join(html.unescape(t).strip() for t in re.findall(r">([^<>]*)</text>", svg)).strip()


async def snapshot(cls: type) -> dict:
    app = Harness(cls)
    try:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause(0.3)
            if app.error:
                return {"error": app.error}
            tree = [type(w).__name__ for w in app.screen.walk_children()]
            return {"tree": tree, "text": _text(app.export_screenshot())}
    except Exception as exc:
        return {"error": _clean(f"{type(exc).__name__}: {exc}")}


async def main() -> None:
    found, errors = targets()
    out = {"import_errors": errors, "classes": {}}
    for name, cls in found.items():
        try:
            out["classes"][name] = await asyncio.wait_for(snapshot(cls), 30)
        except TimeoutError:
            out["classes"][name] = {"error": "timeout"}
    print(json.dumps(out))


if __name__ == "__main__":
    asyncio.run(main())
