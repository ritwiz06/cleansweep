import pandas as pd

from cleansweep.mining import stub


def test_mining_stub_filters_comments():
    comments = pd.DataFrame({"body": ["this is unused", "looks good"]})
    assert len(stub.find_removal_requests(comments)) == 1
    assert len(stub.build_taxonomy(comments)) == 1
