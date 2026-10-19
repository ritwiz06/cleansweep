"""Check that every package (real and stub) exposes the contract names and parameters.

Prints OK / PENDING / FAIL per package. Exit code 1 on FAIL (or on PENDING with --strict).
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys

from cleansweep.core.contracts import INTERFACES


def _params(obj) -> list[str]:
    target = obj.__init__ if inspect.isclass(obj) else obj
    names = list(inspect.signature(target).parameters)
    return [n for n in names if n != "self"]


def check_module(module, spec: dict[str, list[str]]) -> list[str]:
    problems = []
    for name, expected in spec.items():
        obj = module
        for part in name.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                problems.append(f"missing {name}")
                break
        else:
            got = _params(obj)
            if got[: len(expected)] != expected or any(
                p not in expected and _has_no_default(obj, p) for p in got
            ):
                problems.append(f"{name}: expected {expected}, got {got}")
    return problems


def _has_no_default(obj, param: str) -> bool:
    target = obj.__init__ if inspect.isclass(obj) else obj
    p = inspect.signature(target).parameters[param]
    return p.default is inspect.Parameter.empty and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)


def _load(name: str, stub_pkg: str | None = None):
    # import the stub with the switch on, so the package __init__ doesn't need real modules
    for mod in [m for m in sys.modules if m.startswith(name.rsplit(".stub", 1)[0])]:
        del sys.modules[mod]
    if stub_pkg:
        os.environ["CLEANSWEEP_STUBS"] = stub_pkg
    else:
        os.environ.pop("CLEANSWEEP_STUBS", None)
    try:
        return importlib.import_module(name), None
    except ModuleNotFoundError as exc:
        return None, f"PENDING ({exc})"
    except Exception as exc:  # a broken module is a failure, not a pending one
        return None, f"FAIL (import error: {exc})"


def _real_missing(pkg: str) -> bool:
    import cleansweep

    folder = os.path.join(os.path.dirname(cleansweep.__file__), pkg)
    return {f for f in os.listdir(folder) if f.endswith(".py")} <= {"__init__.py", "stub.py"}


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    os.environ.pop("CLEANSWEEP_STUBS", None)
    exit_code = 0
    for pkg, spec in INTERFACES.items():
        for label, modname in (("stub", f"cleansweep.{pkg}.stub"), ("real", f"cleansweep.{pkg}")):
            module, status = _load(modname, pkg if label == "stub" else None)
            if module is not None and label == "real" and _real_missing(pkg):
                module, status = None, "PENDING (real modules not written yet; stub in use)"
            if module is not None:
                problems = check_module(module, spec)
                status = "OK" if not problems else "FAIL: " + "; ".join(problems)
            if status.startswith("FAIL") or (strict and status.startswith("PENDING")):
                exit_code = 1
            print(f"{pkg:<10} {label:<5} {status}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
