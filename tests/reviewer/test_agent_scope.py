from cleansweep.analysis import build_graph
from cleansweep.analysis.scope import agent_scope
from cleansweep.reviewer import run_detectors
from cleansweep.reviewer.planner import review_scope


def keys(items):
    return {(i.category, i.unit.key) for i in items}


def test_agent_scope_reviews_only_the_agent_patch(agent_repo):
    graph = build_graph(agent_repo)
    scoped = keys(run_detectors(agent_repo, graph, agent_scope(agent_repo, graph)))
    assert ("leftover_file", "reproduce_issue.py") in scoped
    assert ("leftover_file", "test_scratch.py") in scoped  # a scratch test at the repo root
    assert ("leftover_file", "sample_app/app.py") in scoped  # a folder the agent created
    assert ("unused_import", "pkg/core.py::os") in scoped
    assert ("dead_code", "pkg/core.py::new_dead") in scoped
    assert ("duplicate", "pkg/core.py::helper_copy") in scoped  # the existing copy is kept
    assert not any(k[1].endswith(("old_unused", "::normalize")) for k in scoped)

    everything = keys(run_detectors(agent_repo, graph))
    assert ("dead_code", "pkg/core.py::old_unused") in everything


def test_scope_setting_defaults_by_target(agent_repo):
    graph = build_graph(agent_repo)
    assert review_scope("swebench:x__y-1:agent_a", agent_repo, graph) is not None
    assert review_scope(f"local:{agent_repo}", agent_repo, graph) is None
