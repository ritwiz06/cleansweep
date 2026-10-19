from cleansweep.analysis import stub


def test_stub_graph():
    g = stub.build_graph(".")
    assert g.units() == [] and g.is_reachable("x")
    assert stub.find_duplicates(".") == []
