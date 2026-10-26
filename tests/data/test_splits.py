from cleansweep.core.models import AgentPatch
from cleansweep.data.splits import candidates, eval_test_command, has_directives, pick

SCRIPT = ": '>>>>> Start Test Output'\n{cmd}\n: '>>>>> End Test Output'\n"


def test_eval_test_command_and_directives():
    assert (
        eval_test_command(SCRIPT.format(cmd="pytest -rA tests/test_a.py"))
        == "pytest -rA tests/test_a.py"
    )
    assert has_directives("pytest -rA tests/test_a.py")
    assert has_directives("./tests/runtests.py --verbosity 2 --parallel 1 auth_tests.test_views")
    assert not has_directives(
        "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1"
    )
    assert has_directives("PYTHONWARNINGS='ignore' bin/test -C sympy/core/tests/test_basic.py")


def make(n_true: int, repo: str, i: int) -> tuple[list[AgentPatch], dict]:
    iid = f"{repo.split('/')[1]}-{i}"
    patches = [AgentPatch(iid, f"agent_{a}", "diff", a < n_true) for a in range(3)]
    row = {"repo": repo, "eval_script": SCRIPT.format(cmd="pytest tests/test_x.py")}
    return patches, {iid: row}


def test_pick_takes_whole_instances_with_the_right_share():
    patches, rows = [], {}
    for i, (n_true, repo) in enumerate(
        [(0, "o/a"), (0, "o/b"), (0, "o/a"), (3, "o/b"), (0, "o/a")]
    ):
        p, r = make(n_true, repo, i)
        patches += p
        rows.update(r)
    groups = candidates(patches, rows)
    tier = pick(groups, rows, size=10, share=0.3, prefer=["o/a", "o/b"])
    assert len(tier) == 10
    assert sum(p.differs_from_oracle for p in tier) == 3
    assert len({p.instance_id for p in tier}) == 4


def test_candidates_skip_unlabeled_and_suite_wide_commands():
    patches, rows = make(0, "o/a", 1)
    patches[0].differs_from_oracle = None
    assert candidates(patches, rows) == {}
    patches, rows = make(0, "o/a", 2)
    rows["a-2"]["eval_script"] = SCRIPT.format(cmd="./tests/runtests.py --parallel 1")
    assert candidates(patches, rows) == {}
