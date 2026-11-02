import pytest

from cleansweep.agents.project_config import FILE_NAME, find, load


def test_the_project_file_is_found_and_read(tmp_path):
    assert find(tmp_path) is None
    path = tmp_path / FILE_NAME
    path.write_text(
        "mode: thorough\n"
        "budget: {llm: 40, minutes: 20, tests: 30}\n"
        "exclude: [tests/fixtures, docs/examples]\n"
        "test_args: \"-m 'not slow'\"\n"
        "install: off\n"
        "model: model-a\n"
    )
    assert find(tmp_path) == path
    assert find(tmp_path, tmp_path / "other.yaml") == tmp_path / "other.yaml"
    assert load(path) == {
        "mode": "thorough",
        "budget": {"llm_calls": 40, "minutes": 20.0, "test_runs": 30},
        "exclude": ["tests/fixtures", "docs/examples"],
        "test_args": "-m 'not slow'",
        "install": "off",
        "model": "model-a",
    }


def test_an_empty_file_has_no_settings(tmp_path):
    (tmp_path / FILE_NAME).write_text("# nothing yet\n")
    assert load(tmp_path / FILE_NAME) == {}


@pytest.mark.parametrize(
    "text,message",
    [
        ("mode: fast\n", "mode must be safe or thorough, got 'fast'"),
        ("budgets: {llm: 3}\n", "unknown setting 'budgets'"),
        ("budget: {cost: 3}\n", "unknown budget item 'cost=3'"),
        ("budget: 100\n", "budget must look like"),
        ("exclude: tests\n", "exclude must be a list of folders"),
        ("model: 3\n", "model must be text"),
        ("- mode\n", "one setting per line"),
        ("mode: [\n", "is not valid YAML"),
    ],
)
def test_bad_settings_name_the_file_and_the_setting(tmp_path, text, message):
    path = tmp_path / FILE_NAME
    path.write_text(text)
    with pytest.raises(ValueError, match=r"\.cleansweep\.yaml") as error:
        load(path)
    assert message in str(error.value)


def test_a_missing_config_file_is_a_readable_error(tmp_path):
    with pytest.raises(ValueError, match="cannot read"):
        load(find(tmp_path, tmp_path / "missing.yaml"))
