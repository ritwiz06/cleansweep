import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "experiments" / "v3" / "exp_inject_v3.py"


def load():
    spec = importlib.util.spec_from_file_location("exp_inject_v3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_benchmark_writes_to_the_v3_folders_only():
    inject = load()
    v2 = inject.load_v2()
    assert v2.RAW == ROOT / "results" / "raw" / "inject_v3"
    assert v2.SUMMARY == ROOT / "results" / "summary" / "v3"
    fresh = importlib.util.spec_from_file_location(
        "exp_inject", ROOT / "scripts" / "experiments" / "v2" / "exp_inject.py"
    )
    original = importlib.util.module_from_spec(fresh)
    fresh.loader.exec_module(original)
    assert original.RAW == ROOT / "results" / "raw" / "inject"


def test_inject_repos_reads_the_split(tmp_path):
    split = tmp_path / "v3_repos.json"
    split.write_text(json.dumps({"inject": [{"full_name": "o/a", "head_sha": "abc"}], "real": []}))
    assert load().inject_repos(split) == {"o/a": "abc"}
