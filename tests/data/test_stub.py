from cleansweep.core.models import FEATURE_COLUMNS
from cleansweep.data import stub


def test_data_stub_shapes():
    assert stub.load_tasks()[0].instance_id
    assert {p.agent for p in stub.load_agent_patches()} == {"agent_a", "agent_b"}
    labels = stub.load_removal_labels()
    assert set(FEATURE_COLUMNS) <= set(labels.columns)
    assert stub.load_history(stub.load_repos()[0])
