"""The v3 repository set: screen more AIDev candidates in Docker, then split them.

    python scripts/data/data_v3_select.py screen [--limit N]
    python scripts/data/data_v3_select.py split

screen: the same seeded sample as data_aidev_select.py, made larger (data.aidev_v3.max_candidates),
minus the candidates v2 already screened, and only those whose license allows local use. Each is
cloned, installed and tested in a container (data_aidev_select.check), and its license and static
layout features are read from git. v2's screened candidates get the features too (no rerun).
Writes data/processed/v3_repo_pool.csv (every row) and results/data_summary/v3_repo_pool.csv
(without the names in data/processed/v3_local_only.txt). Rerunning skips rows already screened.

split: AUTONOMY (diverse layouts, any screen outcome), INJECT and REAL (kept by the screen, not
among v2's runnable repositories), seeded and disjoint, into data/splits/v3_repos.json, with the
other runnable repositories as an ordered reserve: the next one replaces a set member that cannot
be used (for example, too few modules to plant in), so no replacement is picked by hand.
Untrusted code runs only inside the containers; on the host, files are only read from git.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import random
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cleansweep.analysis.graph import is_test_file
from cleansweep.core.config import load_config
from cleansweep.data.aidev import candidates, table
from cleansweep.data.swebench import data_path
from cleansweep.sandbox.aidev_docker import clone_dir

_SELECT = Path(__file__).resolve().parent / "data_aidev_select.py"
FEATURES = [
    "license",
    "test_style",
    "build",
    "layout",
    "notebooks",
    "packages",
    "py_files",
    "test_files",
    "tox",
    "nox",
    "makefile_test",
]
LOCK = threading.Lock()
# screen outcomes that say nothing about how a repository behaves
NOT_SCREENED = ("clone failed", "license", "selection stopped (time or enough repos)")


def _select_module():
    spec = importlib.util.spec_from_file_location("data_aidev_select", _SELECT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(clone: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=clone, capture_output=True, text=True, timeout=120)
    return proc.stdout if proc.returncode == 0 else ""


def features(files: list[str], read) -> dict:
    """Static layout features from a file list and a reader (path -> text)."""
    py = [f for f in files if f.endswith(".py")]
    tests = [f for f in py if is_test_file(f)]
    pyproject = read("pyproject.toml") if "pyproject.toml" in files else ""
    test_text = "\n".join(read(f) for f in tests[:40])
    pytest_config = (
        "[tool.pytest" in pyproject
        or "pytest.ini" in files
        or "[tool:pytest]" in (read("setup.cfg") if "setup.cfg" in files else "")
    )
    if not tests:
        style = "none"
    elif "conftest.py" in {f.rsplit("/", 1)[-1] for f in tests} or pytest_config:
        style = "pytest"
    elif "pytest" in test_text:
        style = "pytest"
    elif "unittest" in test_text:
        style = "unittest"
    else:
        style = "pytest"
    reqs = [f for f in files if re.search(r"(^|/)[^/]*requirements[^/]*\.txt$", f)]
    if "[tool.poetry" in pyproject:
        build = "poetry"
    elif "uv.lock" in files:
        build = "uv"
    elif "pdm.lock" in files:
        build = "pdm"
    elif "hatchling" in pyproject:
        build = "hatch"
    elif "flit_core" in pyproject:
        build = "flit"
    elif "setup.py" in files or "setuptools" in pyproject:
        build = "setuptools"
    elif reqs:
        build = "requirements"
    else:
        build = "none"
    makefile = read("Makefile") if "Makefile" in files else ""
    package_dirs = {
        f.rsplit("/", 1)[0] if "/" in f else "."
        for f in files
        if f.rsplit("/", 1)[-1] in ("pyproject.toml", "setup.py")
    }
    return {
        "test_style": style,
        "build": build,
        "layout": "src" if any(re.match(r"src/[^/]+/__init__\.py$", f) for f in files) else "flat",
        "notebooks": sum(f.endswith(".ipynb") for f in files),
        "packages": len(package_dirs),
        "py_files": len(py),
        "test_files": len(tests),
        "tox": int("tox.ini" in files or "[tool.tox" in pyproject),
        "nox": int("noxfile.py" in files),
        "makefile_test": int(bool(re.search(r"^test[\w-]*\s*:", makefile, re.MULTILINE))),
    }


def repo_features(clone: Path, sha: str) -> dict:
    if not (clone / ".git").exists():
        return {}
    files = _git(clone, "ls-tree", "-r", "--name-only", sha).splitlines()
    return features(files, lambda path: _git(clone, "show", f"{sha}:{path}"))


def license_ok(license_id: str, allowed: list[str]) -> bool:
    return license_id in allowed


def _licenses() -> dict[str, str]:
    repos = table("repository", ("full_name", "license"))
    return {r.full_name: r.license or "" for r in repos.itertuples()}


def _local_only() -> set[str]:
    path = data_path("data/processed/v3_local_only.txt")
    return set(path.read_text().split()) if path.exists() else set()


def _write_summary(rows: list[dict], fields: list[str]) -> None:
    """The committed copy: every row but the names kept local (see DECISIONS)."""
    hidden = _local_only()
    out = data_path("results/data_summary/v3_repo_pool.csv")
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(r for r in rows if r["full_name"] not in hidden)


def screen(cfg: dict, v3: dict, limit: int | None) -> int:
    select = _select_module()
    fields = ["source", *select.FIELDS, *FEATURES]
    pool_csv = data_path("data/processed/v3_repo_pool.csv")
    done = list(csv.DictReader(pool_csv.open())) if pool_csv.exists() else []
    seen = {r["full_name"] for r in done}
    v2_rows = list(csv.DictReader(data_path("results/data_summary/aidev_filter.csv").open()))
    licenses = _licenses()
    new_file = not pool_csv.exists()
    pool_csv.parent.mkdir(parents=True, exist_ok=True)
    f = pool_csv.open("a", newline="")
    writer = csv.DictWriter(f, fieldnames=fields)
    if new_file:
        writer.writeheader()

    def record(rec: dict) -> None:
        with LOCK:
            writer.writerow(rec)
            f.flush()
            print(
                f"{rec['full_name']}: {rec['source']} {rec['status']} {rec['reason']}", flush=True
            )

    for row in v2_rows:
        if row["full_name"] in seen:
            continue
        clone = clone_dir(cfg, row["full_name"])
        feats = repo_features(clone, row["head_sha"]) if row["head_sha"] else {}
        record(
            {"source": "v2 screen", **row, **feats, "license": licenses.get(row["full_name"], "")}
        )
    v2_names = {r["full_name"] for r in v2_rows}
    pool = candidates({**cfg, "max_candidates": v3["max_candidates"]}).to_dict("records")
    todo = []
    for row in pool:
        if row["full_name"] in v2_names or row["full_name"] in seen:
            continue
        lic = licenses.get(row["full_name"], "")
        if not license_ok(lic, v3["licenses"]):
            record(
                {
                    "source": "v3 screen",
                    **{k: row.get(k, "") for k in select.FIELDS},
                    "status": "dropped",
                    "reason": "license",
                    "license": lic,
                }
            )
            continue
        todo.append({**row, "license": lic})
    todo = todo[:limit] if limit else todo
    deadline = time.time() + float(v3["select_hours"]) * 3600
    kept = sum(r["status"] == "kept" and r["source"] == "v3 screen" for r in done)

    def work(row: dict) -> None:
        nonlocal kept
        if time.time() > deadline or kept >= int(v3["target_new_kept"]):
            rec = {
                **{k: row.get(k, "") for k in select.FIELDS},
                "status": "not checked",
                "reason": "selection stopped (time or enough repos)",
            }
        else:
            rec = select.check(row, cfg)
            if rec.get("head_sha"):
                rec |= repo_features(clone_dir(cfg, row["full_name"]), rec["head_sha"])
        with LOCK:
            kept += rec["status"] == "kept"
        record({"source": "v3 screen", **rec, "license": row["license"]})

    with ThreadPoolExecutor(max_workers=int(v3["workers"])) as executor:
        list(executor.map(work, todo))
    f.close()
    rows = list(csv.DictReader(pool_csv.open()))
    _write_summary(rows, fields)
    new_kept = sum(r["status"] == "kept" and r["source"] == "v3 screen" for r in rows)
    print(f"{len(rows)} rows, {new_kept} newly kept -> {pool_csv}")
    return 0


def traits(row: dict) -> set[str]:
    """The AUTONOMY traits a screened repository covers."""
    out = set()
    if row["test_style"] == "none":
        out.add("no_tests")
    if row["test_style"] == "unittest":
        out.add("unittest")
    if row["layout"] == "src":
        out.add("src_layout")
    if row["build"] in ("poetry", "uv", "pdm"):
        out.add("poetry_uv")
    if int(row["notebooks"] or 0):
        out.add("notebooks")
    if int(row["packages"] or 0) >= 2:
        out.add("monorepo")
    if row["reason"] == "install failed":
        out.add("install_failed")
    if int(row["tox"] or 0) or int(row["nox"] or 0) or int(row["makefile_test"] or 0):
        out.add("tox_nox_make")
    return out


def split(rows: list[dict], v3: dict, v2_runnable: set[str], hidden: set[str]) -> dict:
    """Seeded, disjoint INJECT, REAL and AUTONOMY sets from the screened pool."""
    rng = random.Random(int(v3["seed"]))
    usable = [
        r
        for r in rows
        if r["full_name"] not in hidden
        and license_ok(r["license"], v3["licenses"])
        and r["test_style"] != ""
    ]
    usable.sort(key=lambda r: r["full_name"])
    runnable = [
        r
        for r in usable
        if r["status"] == "kept"
        and r["full_name"] not in v2_runnable
        and int(r["py_files"]) >= int(v3["min_py_files"])
        and float(r["test_seconds"] or 0) <= float(v3["max_test_seconds"])
    ]
    rng.shuffle(runnable)
    n_inject, n_real = int(v3["inject"]), int(v3["real"])
    inject, real = runnable[:n_inject], runnable[n_inject : n_inject + n_real]
    reserve = runnable[n_inject + n_real :]  # replacements, in order, for a set member that fails
    taken = {r["full_name"] for r in runnable} | v2_runnable
    rest = [r for r in usable if r["full_name"] not in taken and r["reason"] not in NOT_SCREENED]
    rng.shuffle(rest)
    autonomy: list[dict] = []
    for trait, quota in v3["autonomy_quotas"].items():
        have = sum(trait in traits(r) for r in autonomy)
        for r in rest:
            if have >= quota:
                break
            if r not in autonomy and trait in traits(r):
                autonomy.append(r)
                have += 1
    for r in rest:
        if len(autonomy) >= int(v3["autonomy"]):
            break
        if r not in autonomy:
            autonomy.append(r)

    def entry(r: dict, **extra) -> dict:
        keep = (
            "full_name",
            "head_sha",
            "clone_url",
            "license",
            "status",
            "reason",
            "tests",
            "pass_rate",
            "test_seconds",
            "test_style",
            "build",
            "layout",
            "py_files",
        )
        return {k: r[k] for k in keep} | extra

    runs = int(v3["real_two_runs"])
    return {
        "seed": int(v3["seed"]),
        "inject": [entry(r) for r in inject],
        "real": [entry(r, runs=2 if i < runs else 1) for i, r in enumerate(real)],
        "reserve": [entry(r) for r in reserve],
        "autonomy": [entry(r, traits=sorted(traits(r))) for r in autonomy[: int(v3["autonomy"])]],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=("screen", "split"))
    parser.add_argument("--limit", type=int, help="only the first N new candidates (testing)")
    args = parser.parse_args(argv)
    config = load_config()
    cfg = {**config["data"]["aidev"], **config["core"]["sandbox"]}
    cfg["aidev_clones"] = cfg["clones"]
    v3 = config["data"]["aidev_v3"]
    if args.step == "screen":
        return screen(cfg, v3, args.limit)
    rows = list(csv.DictReader(data_path("data/processed/v3_repo_pool.csv").open()))
    v2_runnable = {
        r["full_name"] for r in json.loads(data_path("data/splits/aidev_repos.json").read_text())
    }
    out = split(rows, v3, v2_runnable, _local_only())
    path = data_path("data/splits/v3_repos.json")
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(
        f"inject {len(out['inject'])}, real {len(out['real'])}, "
        f"autonomy {len(out['autonomy'])} -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
