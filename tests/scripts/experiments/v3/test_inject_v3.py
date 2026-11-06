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


def test_unusable_repositories_are_replaced_from_the_far_end_of_the_reserve(tmp_path, monkeypatch):
    inject = load()
    monkeypatch.setattr(inject, "RAW", tmp_path / "raw")
    split = tmp_path / "v3_repos.json"
    rows = lambda *names: [{"full_name": n, "head_sha": "abc"} for n in names]  # noqa: E731
    split.write_text(
        json.dumps({"inject": rows("o/a", "o/b", "o/c"), "reserve": rows("r/1", "r/2", "r/3")})
    )
    bad = {"o/b": "fewer than 3 importable modules", "r/3": "no valid draw"}
    tried = []

    def prepare_fn(v2, repo, seed, cfg):
        tried.append(repo)
        return bad.get(repo, "")

    assert inject.usable_set(None, 4, {}, split, prepare_fn) == ["o/a", "r/2", "o/c"]
    assert tried == ["o/a", "o/b", "r/3", "r/2", "o/c"]
    written = json.loads((tmp_path / "raw" / "set.json").read_text())
    assert written["set"] == ["o/a", "r/2", "o/c"]
    assert [(r["replaced"], r["by"]) for r in written["replacements"]] == [
        ("o/b", "r/3"),
        ("r/3", "r/2"),
    ]


def test_a_kept_reason_skips_without_a_new_draw(tmp_path, monkeypatch):
    inject = load()
    monkeypatch.setattr(inject, "RAW", tmp_path)
    (tmp_path / "o__a-s4").mkdir()
    (tmp_path / "o__a-s4" / "rejected.txt").write_text("[]")
    (tmp_path / "o__b-s4").mkdir()
    (tmp_path / "o__b-s4" / "skip.txt").write_text("nowhere to plant")

    class V2:
        ATTEMPTS = 3

        def prepare(self, repo, seed, cfg):
            raise AssertionError("no new draw")

    assert "3 draws" in inject.prepared(V2(), "o/a", 4, {})
    assert inject.prepared(V2(), "o/b", 4, {}) == "nowhere to plant"
