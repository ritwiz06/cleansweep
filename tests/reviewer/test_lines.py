import subprocess
from types import SimpleNamespace

from cleansweep.guard.edits import apply_edit
from cleansweep.reviewer.lines import (
    detect_commented_code,
    detect_debug_leftovers,
    detect_redundant_checks,
    detect_todo_notes,
    detect_unused_variables,
    run_line_detectors,
)


def _repo(tmp_path, files):
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return str(tmp_path)


def _apply(repo, item):
    assert item.action == "edit_lines"
    assert apply_edit(SimpleNamespace(path=repo), item)


def test_unused_variables_keep_calls_and_handlers(tmp_path):
    repo = _repo(
        tmp_path,
        {
            "pkg/m.py": (
                "def f(x):\n    unused = x * 2\n    result = compute(x)\n"
                "    try:\n        return x\n"
                "    except ValueError as err:\n        return None\n\n\n"
                "def compute(x):\n    return x\n"
            )
        },
    )
    items = detect_unused_variables(repo)
    assert {i.unit.start_line for i in items} == {2, 3, 6} and all(i.lane == "safe" for i in items)
    for item in sorted(items, key=lambda i: i.unit.start_line):  # top-down: lines move
        _apply(repo, item)
    text = (tmp_path / "pkg/m.py").read_text()
    assert "unused" not in text and "    compute(x)\n" in text and "except ValueError:" in text
    compile(text, "m.py", "exec")


def test_an_unused_name_for_a_multi_line_call_keeps_the_call(tmp_path):
    source = (
        "def f(db, run):\n    if run:\n        ref = db.upsert(\n            run, 1\n        )\n"
        "    return run\n"
    )
    repo = _repo(tmp_path, {"pkg/m.py": source})
    (item,) = detect_unused_variables(repo)
    _apply(repo, item)
    text = (tmp_path / "pkg/m.py").read_text()
    assert text == source.replace("ref = db.upsert(", "db.upsert(")
    compile(text, "m.py", "exec")


def test_debug_leftovers(tmp_path):
    repo = _repo(
        tmp_path,
        {
            "pkg/lib.py": (
                "def f(x):\n    breakpoint()\n    print(f'{x=}')\n    print('DEBUG got', x)\n"
                "    print('total:', x)\n    return x\n\n\ndef g():\n    print('debug')\n"
            ),
            "pkg/cli.py": "def main():\n    print('total: 3')\n    print(f'{a}  method={a}')\n",
        },
    )
    items = detect_debug_leftovers(repo)
    lanes = {(i.unit.path, i.unit.start_line): i.lane for i in items}
    assert (
        lanes[("pkg/lib.py", 2)] == lanes[("pkg/lib.py", 3)] == lanes[("pkg/lib.py", 4)] == "safe"
    )
    assert lanes[("pkg/lib.py", 5)] == "suggest"  # may be intended output
    assert ("pkg/cli.py", 2) not in lanes and (
        "pkg/cli.py",
        3,
    ) not in lanes  # a CLI prints on purpose
    _apply(repo, next(i for i in items if i.unit.start_line == 10))
    assert (
        "    pass\n" in (tmp_path / "pkg/lib.py").read_text()
    )  # the emptied body keeps a statement


def test_a_debugger_call_behind_a_switch_is_only_suggested(tmp_path):
    repo = _repo(
        tmp_path,
        {
            "pkg/hooks.py": (
                "import pdb\n\n\nclass Hook:\n    def __call__(self, x):\n"
                "        if self.debug_on_nan:\n            print('Entering debugger...')\n"
                "            pdb.set_trace()\n        return x\n\n\n"
                "def g(x):\n    pdb.set_trace()\n    return x\n"
            )
        },
    )
    calls = [i for i in detect_debug_leftovers(repo) if "set_trace" in i.reason]
    assert {i.unit.start_line: i.lane for i in calls} == {8: "suggest", 13: "safe"}


def test_commented_code_but_not_prose(tmp_path):
    repo = _repo(
        tmp_path,
        {
            "pkg/m.py": (
                "# Copyright 2026 someone\n"
                "def f(x):\n"
                "    # Compute the total, then round it.\n"
                "    # old = x * 2\n"
                "    # return round(old)\n"
                "    return x  # noqa: E501\n"
                "# type: ignore\n"
            )
        },
    )
    items = detect_commented_code(repo)
    assert [(i.unit.start_line, i.unit.end_line) for i in items] == [(4, 5)]
    _apply(repo, items[0])
    text = (tmp_path / "pkg/m.py").read_text()
    assert "old = x" not in text and "Compute the total" in text


def test_prose_that_parses_and_output_prints_stay(tmp_path):
    repo = _repo(
        tmp_path,
        {
            "pkg/m.py": (
                "def f(x, n):\n"
                "    # Common patterns:\n"
                "    # - name(param1, param2)\n"
                "    # Paragraph (default)\n"
                "    # Links [text](url)\n"
                "    # Author(s)\n"
                "    # os.system('clear' if os.name != 'nt' else 'cls')\n"
                "    print(f'Creating index (dimension={n})')\n"
                "    print(f'\\n--- Extracting content for: {x}')\n"
                "    return x\n"
            )
        },
    )
    assert [(i.unit.start_line, i.unit.end_line) for i in detect_commented_code(repo)] == [(7, 7)]
    assert {i.lane for i in detect_debug_leftovers(repo)} == {"suggest"}  # output, not debugging


def test_todo_notes_are_suggestions(tmp_path):
    repo = _repo(
        tmp_path,
        {"m.py": "x = 1\n# TODO: remove this hack\n# FIXME later\ny = 2  # TODO inline stays\n"},
    )
    items = detect_todo_notes(repo)
    assert [i.unit.start_line for i in items] == [2, 3] and {i.lane for i in items} == {"suggest"}


def test_redundant_checks(tmp_path):
    repo = _repo(
        tmp_path,
        {
            "m.py": (
                "def a(x):\n    if x > 1:\n        return True\n"
                "    else:\n        return False\n\n\n"
                "def b(x):\n    if x:\n        return False\n    return True\n\n\n"
                "def c(x, y):\n    return x and x\n\n\n"
                "def d(flag):\n    return flag == True\n"
            )
        },
    )
    items = detect_redundant_checks(repo)
    by_line = {i.unit.start_line: i for i in items}
    assert by_line[2].lane == by_line[9].lane == by_line[15].lane == "safe"
    assert by_line[19].lane == "suggest"  # x == True is not x for non-bool values
    for line in (15, 9, 2):
        _apply(repo, by_line[line])
    text = (tmp_path / "m.py").read_text()
    assert "return bool(x > 1)" in text and "return not (x)" in text and "return x\n" in text
    ns = {}
    exec(text, ns)
    assert (
        ns["a"](2) is True and ns["a"](0) is False and ns["b"](0) is True and ns["b"]("s") is False
    )


def test_tests_and_syntax_errors_are_skipped(tmp_path):
    repo = _repo(
        tmp_path, {"tests/test_m.py": "def test_x():\n    print('debug')\n", "bad.py": "def (:\n"}
    )
    assert run_line_detectors(repo) == []


def test_edit_lines_refuses_when_the_old_lines_are_gone(tmp_path):
    repo = _repo(tmp_path, {"m.py": "def f(x):\n    unused = 1\n    return x\n"})
    item = detect_unused_variables(repo)[0]
    (tmp_path / "m.py").write_text("def f(x):\n    return x\n")
    assert not apply_edit(SimpleNamespace(path=repo), item)
    assert (tmp_path / "m.py").read_text() == "def f(x):\n    return x\n"


def test_inline_script_metadata_is_not_commented_code(tmp_path):
    repo = _repo(
        tmp_path,
        {
            "bench.py": (
                "# /// script\n"
                '# requires-python = ">=3.11"\n'
                '# dependencies = ["pandas", "seaborn"]\n'
                "# ///\n"
                "import sys\n\n"
                "# old = sys.argv[1]\n"
                "# print(old)\n"
            )
        },
    )
    items = detect_commented_code(repo)
    assert [(i.unit.start_line, i.unit.end_line) for i in items] == [(7, 8)]
