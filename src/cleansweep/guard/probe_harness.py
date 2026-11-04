"""Run probe modules against the code in the current folder and write their results as JSON.

Standalone on purpose: it is copied into the workspace and run with the target project's own
Python (which may be as old as 3.6 inside a SWE-bench container), so it uses only the
standard library and no newer syntax.

Usage: python probe_harness.py SPEC.json
The spec lists probe files, name swaps and modules to list, all relative to the current folder,
and optionally standalone scripts to load by path first (see load_script).
In runner mode a generated test file calls main(spec, root) inside the project's own test run;
main then puts back what it changed (cwd, sys.path, sockets, the alarm handler).
"""

import importlib
import importlib.util
import json
import os
import re
import shutil
import signal
import socket
import sys
import tempfile
import types

_TIMER = {"on": False}  # True once the alarm handler is installed
ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+|0x[0-9a-fA-F]{6,}")
MAX_LEN = 400


class CaseTimeout(Exception):
    pass


def _alarm(signum, frame):
    raise CaseTimeout()


def _no_network(*args, **kwargs):
    raise OSError("probes may not use the network")


def normalize(value, depth=0):
    """A repr that is the same across runs: no memory addresses, sorted dicts and sets."""
    if depth > 6:
        return "..."
    if value is None or isinstance(value, (bool, int, float, complex, str, bytes)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        inner = ", ".join(normalize(v, depth + 1) for v in value)
        return f"[{inner}]" if isinstance(value, list) else f"({inner})"
    if isinstance(value, dict):
        pairs = sorted(
            f"{normalize(k, depth + 1)}: {normalize(v, depth + 1)}" for k, v in value.items()
        )
        return "{" + ", ".join(pairs) + "}"
    if isinstance(value, (set, frozenset)):
        return "set(" + ", ".join(sorted(normalize(v, depth + 1) for v in value)) + ")"
    if isinstance(value, types.GeneratorType):
        items = []
        for i, v in enumerate(value):
            if i >= 100:
                break
            items.append(v)
        return "gen" + normalize(items, depth + 1)
    try:
        text = repr(value)
    except Exception as exc:
        return f"repr raises {type(exc).__name__}"
    if " object at 0x" in text and hasattr(value, "__dict__"):
        return f"{type(value).__name__}({normalize(vars(value), depth + 1)})"
    return ADDRESS.sub("", text)


def _short(text):
    return text if len(text) <= MAX_LEN else text[:MAX_LEN] + "..."


def _error(exc):
    return f"{type(exc).__name__}: {_short(str(exc))}"


def _import(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        if name in sys.modules:
            return sys.modules[name]
        module = types.ModuleType(name)  # the module was deleted; give the swap a home
        sys.modules[name] = module
        return module


class _Missing(types.ModuleType):
    """Stands in for a third-party module a standalone script imports but this environment
    lacks (say a PEP 723 dependency): every attribute is a mock."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        from unittest import mock

        value = mock.MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, value)
        return value


class _StubFinder:
    """Last on sys.meta_path: answers only for the stubbed top-level names."""

    def __init__(self):
        self.names = set()

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] not in self.names:
            return None
        return importlib.util.spec_from_loader(fullname, self, is_package=True)

    def create_module(self, spec):
        return _Missing(spec.name)

    def exec_module(self, module):
        pass


_STUBS = _StubFinder()
_LOADED = []  # scripts loaded by path, removed again at the end (runner mode shares a process)


def _local(name, root):
    """A name the project itself provides: never stubbed, its import error is real."""
    for base in (root, os.path.join(root, "src")):
        if os.path.exists(os.path.join(base, name)) or os.path.exists(
            os.path.join(base, name + ".py")
        ):
            return True
    return False


def load_script(name, path, root):
    """Load a standalone script by path as module `name`. Its __name__ is not "__main__", so
    its main block does not run; its folder goes on sys.path for sibling imports; third-party
    modules it imports that are missing here are stubbed (and listed)."""
    folder = os.path.dirname(path)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    if _STUBS not in sys.meta_path:
        sys.meta_path.append(_STUBS)
    stubbed = []
    for _ in range(20):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            _LOADED.append(name)
            return {"ok": True, "stubbed": stubbed}
        except ImportError as exc:
            sys.modules.pop(name, None)
            missing = (getattr(exc, "name", None) or "").split(".")[0]
            if not missing or missing in _STUBS.names or _local(missing, root):
                return {"ok": False, "error": _error(exc), "stubbed": stubbed}
            _STUBS.names.add(missing)
            stubbed.append(missing)
        except BaseException as exc:
            sys.modules.pop(name, None)
            return {"ok": False, "error": _error(exc), "stubbed": stubbed}
    return {"ok": False, "error": "too many missing modules", "stubbed": stubbed}


def _drop_stubs():
    for name in _LOADED:
        sys.modules.pop(name, None)
    del _LOADED[:]
    if _STUBS in sys.meta_path:
        sys.meta_path.remove(_STUBS)
    for name in list(sys.modules):
        if name.split(".")[0] in _STUBS.names:
            del sys.modules[name]
    _STUBS.names.clear()


def apply_swap(swap):
    """Bind module.name to the value of an expression in another module (the kept copy)."""
    source = importlib.import_module(swap["source_module"])
    value = eval(swap["source_expr"], vars(source))
    setattr(_import(swap["module"]), swap["name"], value)


def run_probe(path, max_cases, case_timeout):
    name = f"_cs_probe_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        cases = list(module.make_cases())[:max_cases]
    except BaseException as exc:
        return {"ok": False, "error": _error(exc)}
    results = {}
    for i, case in enumerate(cases):
        try:
            label, fn = case
            label = str(label)
        except Exception:
            label, fn = f"case {i}", None
        if label in results:
            label = f"{label} #{i}"
        if not callable(fn):
            results[label] = "not callable"
            continue
        if _TIMER["on"]:
            signal.alarm(case_timeout)
        try:
            results[label] = _short(normalize(fn()))
        except CaseTimeout:
            results[label] = "timeout"
        except BaseException as exc:
            results[label] = f"raises {type(exc).__name__}"
        finally:
            if _TIMER["on"]:
                signal.alarm(0)
    return {"ok": True, "cases": results}


def list_module(name):
    try:
        module = importlib.import_module(name)
        found = vars(module)
        names = sorted(n for n in found if not n.startswith("_"))
        # type(), not isinstance(): lazy objects (Django's settings) set themselves up on isinstance
        modules = [n for n in names if issubclass(type(found[n]), types.ModuleType)]
    except BaseException as exc:
        return {"ok": False, "error": _error(exc)}
    return {"ok": True, "names": names, "modules": modules}


def main(spec_path, root=None):
    saved = (
        os.getcwd(),
        list(sys.path),
        socket.socket.connect,
        socket.create_connection,
        signal.getsignal(signal.SIGALRM),
    )
    scratch = tempfile.mkdtemp(prefix="cs_probe_")  # stray file writes land outside the repo
    try:
        _run(spec_path, root or os.getcwd(), scratch)
    finally:
        cwd, path, connect, create, handler = saved
        os.chdir(cwd)
        shutil.rmtree(scratch, ignore_errors=True)
        sys.path[:] = path
        socket.socket.connect = connect
        socket.create_connection = create
        if _TIMER["on"]:
            signal.signal(signal.SIGALRM, handler)
            _TIMER["on"] = False
        _drop_stubs()


def _run(spec_path, root, scratch):
    with open(spec_path) as f:
        spec = json.load(f)
    for extra in reversed(spec.get("paths", ["."])):
        sys.path.insert(0, os.path.join(root, extra))
    out_path = os.path.join(root, spec["out"])
    probe_files = [(p["id"], os.path.join(root, p["file"])) for p in spec.get("probes", [])]
    os.environ["PYTHONHASHSEED"] = "0"
    socket.socket.connect = _no_network
    socket.create_connection = _no_network
    try:
        signal.signal(signal.SIGALRM, _alarm)
        _TIMER["on"] = True
    except ValueError:  # not the main thread: cases run without a timeout
        pass
    os.chdir(scratch)

    out = {"modules": {}, "probes": {}, "swaps": []}
    for name, rel in sorted(spec.get("scripts", {}).items()):
        out.setdefault("scripts", {})[name] = load_script(name, os.path.join(root, rel), root)
    for name in spec.get("modules", []):
        out["modules"][name] = list_module(name)
    swap_error = None
    for swap in spec.get("swaps", []):
        try:
            apply_swap(swap)
            out["swaps"].append({"ok": True})
        except BaseException as exc:
            swap_error = f"swap {swap['module']}.{swap['name']} failed: {_error(exc)}"
            out["swaps"].append({"ok": False, "error": _short(swap_error)})
    max_cases = int(spec.get("max_cases", 8))
    case_timeout = int(spec.get("case_timeout", 10))
    for probe_id, path in probe_files:
        if swap_error:
            out["probes"][probe_id] = {"ok": False, "error": swap_error}
        else:
            out["probes"][probe_id] = run_probe(path, max_cases, case_timeout)
    with open(out_path, "w") as f:
        json.dump(out, f)


if __name__ == "__main__":
    main(sys.argv[1])
