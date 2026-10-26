from cleansweep.analysis import build_graph
from cleansweep.analysis.minhash import find_duplicates
from cleansweep.analysis.scope import agent_commit, agent_scope


def test_scope_covers_only_what_the_agent_wrote(agent_repo):
    assert agent_commit(agent_repo)
    scope = agent_scope(agent_repo, build_graph(agent_repo))
    assert scope.files_added == {"reproduce_issue.py", "test_scratch.py", "sample_app/app.py"}
    assert scope.outside_project("sample_app/app.py") and scope.outside_project("test_scratch.py")
    assert not scope.outside_project("pkg/core.py")
    assert "pkg/core.py::helper_copy" in scope.units and "pkg/core.py::new_dead" in scope.units
    assert "pkg/core.py::old_unused" not in scope.units
    assert "pkg/core.py::normalize" not in scope.units


def test_no_agent_commit_means_no_scope(toy_ws):
    assert agent_scope(toy_ws.path, build_graph(toy_ws.path)) is None


def test_find_duplicates_k_by_n(agent_repo):
    pairs = find_duplicates(agent_repo, 0.8, only={"pkg/core.py::helper_copy"})
    assert {(a.key, b.key) for a, b, _ in pairs} == {
        ("pkg/core.py::helper_copy", "pkg/core.py::normalize")
    }
