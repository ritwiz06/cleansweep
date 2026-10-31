import pytest

from cleansweep.agents.cache import ArtifactCache


def test_the_same_content_gives_the_same_id_and_comes_back(tmp_path):
    cache = ArtifactCache(tmp_path)
    first = cache.put("diff", "--- a\n+++ b\n")
    assert cache.put("diff", "--- a\n+++ b\n") == first
    assert first.startswith("art:diff:") and cache.get(first) == "--- a\n+++ b\n"
    brief = cache.put("brief", {"name": "shop", "frameworks": ["flask"]})
    assert cache.get(brief) == {"name": "shop", "frameworks": ["flask"]}
    assert sorted(cache.ids()) == sorted([first, brief])


def test_digest_and_slice_stay_short(tmp_path):
    cache = ArtifactCache(tmp_path)
    art = cache.put("test_log", "\n".join(f"line {n}" for n in range(1, 1001)))
    assert len(cache.digest(art)) <= 300
    part = cache.slice(art, 10, 12)
    assert "10: line 10" in part and "12: line 12" in part and "13: line 13" not in part
    assert len(cache.slice(art, 1, 900).splitlines()) <= 201


def test_unknown_ids_raise(tmp_path):
    cache = ArtifactCache(tmp_path)
    with pytest.raises(KeyError):
        cache.get("art:diff:00000000")


def test_stored_artifacts_are_redacted(tmp_path):
    cache = ArtifactCache(tmp_path, redact=lambda text: text.replace("hunter2", "[REDACTED]"))
    art = cache.put("test_log", "password is hunter2")
    assert "hunter2" not in cache.text(art)
