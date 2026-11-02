import pytest

from app.studio.files import Forbidden, clean, events, read_text, resolve


@pytest.fixture
def roots(tmp_path):
    base = tmp_path / "runs"
    (base / "run").mkdir(parents=True)
    (base / "run" / "notes.md").write_text("hello")
    return {"runs": base}


@pytest.mark.parametrize(
    "rel",
    ["../outside.txt", "run/../../outside.txt", "/etc/hosts", ".env", "run/.env", "a\x00b"],
)
def test_resolve_refuses_escapes_and_hidden_files(roots, rel):
    with pytest.raises(Forbidden):
        resolve(roots, "runs", rel)


def test_resolve_refuses_secret_files_and_links_to_them(roots, tmp_path):
    base = roots["runs"]
    (base / "keys.pem").write_text("x")
    (base / ".hidden").write_text("x")
    (base / "notes.txt").symlink_to(base / ".hidden")
    (tmp_path / "outside.txt").write_text("x")
    (base / "out.txt").symlink_to(tmp_path / "outside.txt")
    for rel in ("keys.pem", "notes.txt", "out.txt"):
        with pytest.raises(Forbidden):
            resolve(roots, "runs", rel)
    with pytest.raises(Forbidden):
        resolve(roots, "nowhere", "run")
    assert resolve(roots, "runs", "run/notes.md").read_text() == "hello"


def test_clean_and_read_text_redact_secrets(tmp_path):
    key = "AK" + "IA" + "Q7" * 8
    assert key not in str(clean({"a": [f"key {key}"]}))
    path = tmp_path / "log.txt"
    path.write_text(f"token = '{'z9' * 8}'\n" + "x" * 50)
    out = read_text(path, limit=30)
    assert "z9z9z9" not in out["text"] and out["truncated"]


def test_events_skip_a_half_written_line_and_redact(tmp_path):
    key = "AK" + "IA" + "Q7" * 8
    path = tmp_path / "events.jsonl"
    path.write_text(f'{{"kind": "log", "payload": {{"m": "{key}"}}}}\n{{"kin')
    found = events(path)
    assert len(found) == 1 and key not in str(found)
