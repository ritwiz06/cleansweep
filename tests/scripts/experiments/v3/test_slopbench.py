import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "experiments" / "v3" / "slopbench.py"


def load():
    spec = importlib.util.spec_from_file_location("slopbench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rows_list_each_repository_at_its_commit_with_its_license():
    bench = load()
    v2_split = [{"full_name": "o/a", "head_sha": "a1", "clone_url": "https://x/o/a.git"}]
    v3_split = {
        "inject": [
            {
                "full_name": "o/b",
                "head_sha": "b1",
                "license": "MIT",
                "clone_url": "https://x/o/b.git",
            }
        ]
    }
    pool = [{"full_name": "o/a", "license": "nan"}]
    out = bench.rows(["toy", "o/a"], v2_split, v3_split, pool)
    assert [(r["repo"], r["seeds"], r["commit"], r["license"]) for r in out] == [
        ("o/a", "1 2 3", "a1", "none detected"),
        ("o/b", "4", "b1", "MIT"),
    ]
