"""Snapshot a Textual app's screens and widgets headless; runs in the project's environment.

    python ui_harness.py '["pkg.ui.screens", "pkg.ui.widgets"]'

Every class defined in the given modules that is a Textual widget (screens included) is mounted
in a small app under App.run_test. A class that needs arguments gets a placeholder for each
required one, chosen by its annotation (the same in every run). Its snapshot is the widget tree
and the visible text of the screen. A module that does not import, or a class that fails to
build or mount, is recorded with the error's type and message. The result is printed as one
line: CS_UI_JSON {...}.
"""

import asyncio
import html
import importlib
import inspect
import json
import os
import re
import sys

MARK = "CS_UI_JSON "
SIZE = (100, 32)
CLASS_TIMEOUT_S = 30


def _clean(text: str) -> str:
    return re.sub(r"0x[0-9a-f]+", "0x", text)[:300]


def targets(modules: list) -> tuple:
    from textual.widget import Widget

    found, errors = {}, {}
    for name in modules:
        try:
            mod = importlib.import_module(name)
        except BaseException as exc:
            errors[name] = _clean(f"{type(exc).__name__}: {exc}")
            continue
        for attr, obj in sorted(vars(mod).items()):
            if inspect.isclass(obj) and obj.__module__ == mod.__name__ and issubclass(obj, Widget):
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


def _text(svg: str) -> str:
    parts = (html.unescape(t).replace("\xa0", " ") for t in re.findall(r">([^<>]*)</text>", svg))
    return " ".join(p.strip() for p in parts).strip()


async def snapshot(cls: type) -> dict:
    from textual.app import App
    from textual.screen import Screen

    class Harness(App):
        error = None

        def on_mount(self) -> None:
            try:
                obj = build(cls)
            except Exception as exc:
                self.error = _clean(f"build: {type(exc).__name__}: {exc}")
                return
            if isinstance(obj, Screen):
                self.push_screen(obj)
            else:
                self.mount(obj)

    app = Harness()
    try:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause(0.3)
            if app.error:
                return {"error": app.error}
            tree = [type(w).__name__ for w in app.screen.walk_children()]
            return {"tree": tree, "text": _text(app.export_screenshot())}
    except Exception as exc:
        return {"error": _clean(f"{type(exc).__name__}: {exc}")}


async def main(modules: list) -> dict:
    found, errors = targets(modules)
    out = {"import_errors": errors, "classes": {}}
    for name, cls in found.items():
        try:
            out["classes"][name] = await asyncio.wait_for(snapshot(cls), CLASS_TIMEOUT_S)
        except (asyncio.TimeoutError, TimeoutError):  # noqa: UP041 (they differ before 3.11)
            out["classes"][name] = {"error": "timeout"}
    return out


if __name__ == "__main__":
    for folder in ("src", "."):
        if os.path.isdir(folder):
            sys.path.insert(0, os.path.abspath(folder))
    result = asyncio.run(main(json.loads(sys.argv[1])))
    print(MARK + json.dumps(result, sort_keys=True))
