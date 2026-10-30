import pytest

from cleansweep.reviewer import run_detectors


def test_planted_items_found(toy_repo, toy_expected):
    items = {i.unit.key: i for i in run_detectors(toy_repo)}
    planted_safe = [r for r in toy_expected if r["expected_lane"] == "safe"]
    found = [r for r in planted_safe if r["key"] in items]
    assert len(found) / len(planted_safe) >= 0.9
    for row in toy_expected:
        if row["key"] in items:
            assert items[row["key"]].category == row["category"], row["key"]
            assert items[row["key"]].lane == row["expected_lane"], row["key"]


def test_traps_and_security_not_auto_deleted(toy_repo):
    items = {i.unit.key: i for i in run_detectors(toy_repo)}
    trap = items["shopcart/commands.py::cmd_export"]
    assert trap.lane == "suggest" and any("dynamic" in e for e in trap.evidence)
    sec = items["shopcart/storage.py::load_legacy"]
    assert sec.lane == "suggest" and sec.action == "report_only"


def test_items_have_evidence_and_stable_ids(toy_repo):
    first = run_detectors(toy_repo)
    second = run_detectors(toy_repo)
    assert [i.item_id for i in first] == [i.item_id for i in second]
    assert all(i.evidence and i.reason for i in first)


def test_dependency_evidence_mentions_configs(tmp_path):
    from cleansweep.reviewer.detectors import _dependency_mentions

    (tmp_path / "requirements.txt").write_text("gunicorn\nrequests\n")
    (tmp_path / "Dockerfile").write_text("CMD gunicorn app:app\n")
    assert _dependency_mentions(str(tmp_path), "gunicorn", "requirements.txt") == [
        "gunicorn is mentioned in Dockerfile"
    ]
    assert "not mentioned" in _dependency_mentions(str(tmp_path), "requests", "requirements.txt")[0]


def _api_repo(tmp_path, metadata: str | None = None):
    for path in (
        "pkg/__init__.py",
        "pkg/mod.py",
        "pkg/_private.py",
        "scripts/__init__.py",
        "scripts/run.py",
        "bad-name/__init__.py",
        "bad-name/mod.py",
        "loose.py",
    ):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("")
    if metadata:
        (tmp_path / "pyproject.toml").write_text(metadata)
    return str(tmp_path)


def test_is_public_api_needs_a_public_name_in_a_package_module(tmp_path):
    from cleansweep.core.models import CodeUnit
    from cleansweep.reviewer.detectors import is_public_api

    repo = _api_repo(tmp_path)
    public = [("pkg/mod.py", "function", "helper"), ("pkg/mod.py", "function", "Box.size")]
    private = [
        ("pkg/mod.py", "function", "_helper"),  # private name
        ("pkg/mod.py", "function", "Box._size"),
        ("pkg/_private.py", "function", "helper"),  # private module
        ("scripts/run.py", "function", "main"),  # a script folder
        ("bad-name/mod.py", "function", "helper"),  # not importable
        ("loose.py", "function", "helper"),  # not in a package
        ("pkg/mod.py", "import", "os"),
    ]
    assert all(is_public_api(repo, CodeUnit(p, k, n)) for p, k, n in public)
    assert not any(is_public_api(repo, CodeUnit(p, k, n)) for p, k, n in private)


def test_keep_public_api_moves_public_dead_code_to_suggest(tmp_path):
    from cleansweep.core.models import CodeUnit
    from cleansweep.reviewer.detectors import PUBLIC_API_REASON, keep_public_api, make_item

    def items():
        return [
            make_item(CodeUnit("pkg/mod.py", "function", n), c, "delete_unit", "safe", "r", [], [])
            for n, c in (("helper", "dead_code"), ("_helper", "dead_code"), ("dup", "duplicate"))
        ]

    packaged = _api_repo(tmp_path / "a", '[project]\nname = "pkg"\n')
    plain = _api_repo(tmp_path / "b")
    moved = keep_public_api(items(), packaged)  # auto, with packaging metadata
    assert [i.lane for i in moved] == ["suggest", "safe", "safe"]
    assert moved[0].reason == PUBLIC_API_REASON
    assert [i.lane for i in keep_public_api(items(), plain)] == ["safe"] * 3  # auto, no metadata
    assert [i.lane for i in keep_public_api(items(), plain, "on")][0] == "suggest"
    assert [i.lane for i in keep_public_api(items(), packaged, "off")][0] == "safe"
    # YAML reads a bare on/off as a bool
    assert [i.lane for i in keep_public_api(items(), packaged, False)][0] == "safe"
    assert [i.lane for i in keep_public_api(items(), plain, True)][0] == "suggest"
    with pytest.raises(ValueError, match="keep_public_api"):
        keep_public_api(items(), packaged, "sometimes")


def test_has_package_metadata(tmp_path):
    from cleansweep.reviewer.detectors import has_package_metadata

    assert not has_package_metadata(str(tmp_path))
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    assert not has_package_metadata(str(tmp_path))  # a tool config only
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = x\n")
    assert has_package_metadata(str(tmp_path))


def test_keep_framework_callbacks_moves_callbacks_to_suggest(tmp_path):
    from cleansweep.analysis import build_graph
    from cleansweep.core.models import CodeUnit
    from cleansweep.reviewer.detectors import keep_framework_callbacks, make_item

    (tmp_path / "ui.py").write_text(
        "from textual.app import App\n\nclass Main(App):\n    def on_mount(self):\n"
        "        pass\n\n    def helper(self):\n        pass\n"
    )
    graph = build_graph(str(tmp_path))

    def items():
        return [
            make_item(
                CodeUnit("ui.py", "function", n), "dead_code", "delete_unit", "safe", "r", [], []
            )
            for n in ("Main.on_mount", "Main.helper")
        ]

    moved = keep_framework_callbacks(items(), graph)
    assert [i.lane for i in moved] == ["suggest", "safe"]
    assert moved[0].reason.startswith("textual calls this method by name")
    assert [i.lane for i in keep_framework_callbacks(items(), graph, "off")] == ["safe", "safe"]
    assert [i.lane for i in keep_framework_callbacks(items(), graph, False)] == ["safe", "safe"]
    with pytest.raises(ValueError, match="framework_callbacks"):
        keep_framework_callbacks(items(), graph, "auto")


def test_formatting_follows_the_project_line_length(tmp_path):
    from cleansweep.reviewer.detectors import detect_formatting

    long_call = "combined_result = compute(" + ", ".join(f"argument_{i}" for i in range(6)) + ")\n"
    assert 88 < len(long_call.strip()) < 100
    (tmp_path / "mod.py").write_text(long_call)
    assert [i.unit.path for i in detect_formatting(str(tmp_path))] == ["mod.py"]
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    assert detect_formatting(str(tmp_path)) == []
