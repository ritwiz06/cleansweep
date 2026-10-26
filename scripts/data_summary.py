"""Print PatchDiff patch counts per agent, per repo and per label.

python scripts/data_summary.py
"""

from __future__ import annotations

from collections import Counter

from cleansweep.data import load_agent_patches
from cleansweep.data.swebench import load_rows


def main() -> int:
    repos = {r["instance_id"]: r["repo"] for r in load_rows()}
    patches = load_agent_patches()
    print(f"{len(patches)} plausible patches")
    for title, counts in (
        ("per agent", Counter(p.agent for p in patches)),
        ("per repo", Counter(repos.get(p.instance_id, "?") for p in patches)),
        ("per label (differs_from_oracle)", Counter(str(p.differs_from_oracle) for p in patches)),
    ):
        print(f"\n{title}:")
        for key, n in counts.most_common():
            print(f"  {key:30} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
