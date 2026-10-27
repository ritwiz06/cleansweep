from cleansweep.core.models import CommitEvent
from cleansweep.scheduler import replay


def history(n=6):
    days = ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02", "2026-01-03", "2026-01-03"]
    return [
        CommitEvent(
            f"c{i}",
            f"{days[i]}T10:00:00+00:00",
            i % 2 == 1,
            "agent_a" if i % 2 else None,
            i if i % 2 else None,
        )
        for i in range(n)
    ]


def fake_snapshots(items_at):
    def snaps(history, repo_dir, cfg=None):
        return {
            i: {
                "items": {k: ["dead_code", f"m.py::{k}", 10] for k in keys},
                "loc": 100,
                "files": ["m.py"],
            }
            for i, keys in items_at.items()
        }

    return snaps


def test_policies(monkeypatch):
    # slop appears at commit 1 (a), grows at 3 (b); "a" is used again by commit 5
    monkeypatch.setattr(
        replay, "snapshots", fake_snapshots({0: [], 1: ["a"], 3: ["a", "b"], 5: ["b"]})
    )
    h = history()
    none = replay.simulate(h, "x", "none")
    assert none["sweeps"] == 0 and none["slop_debt"] == 1 + 1 + 2 + 2 + 1
    every_pr = replay.simulate(h, "x", "every_pr")
    assert every_pr["sweeps"] == 2 and every_pr["final_slop"] == 0
    assert every_pr["resurrected"] == 1 and every_pr["resurrection_rate"] == 0.5  # "a" came back
    every_n = replay.simulate(h, "x", "every_n", {"every_n": 5})
    assert every_n["sweeps"] == 0
    daily = replay.simulate(h, "x", "daily")
    # nightly sweeps before c2 ("a") and c4 ("b"); each stays open for one commit
    assert daily["sweeps"] == 2 and daily["slop_debt"] == 2 and daily["final_slop"] == 0
    adaptive = replay.simulate(h, "x", "adaptive", {"adaptive_threshold": 0.15})
    assert adaptive["sweeps"] == 1  # 20 of 100 lines at commit 3


def test_measured_points():
    assert replay.measured_points(history(6), 3) == [0, 2, 4, 5]
    assert replay.measured_points([], 3) == []
