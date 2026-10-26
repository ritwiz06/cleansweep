"""Write the SWE-bench tiers to data/splits/ (tier 1 inside tier 2 inside tier 3).

python scripts/data_make_splits.py
"""

from __future__ import annotations

from collections import Counter

from cleansweep.core.config import load_config
from cleansweep.data import load_agent_patches
from cleansweep.data.splits import candidates, pick, tasks_tier, write_tier
from cleansweep.data.swebench import data_path, load_rows


def main() -> int:
    cfg = load_config()["data"]["splits"]
    rows = {r["instance_id"]: r for r in load_rows()}
    groups = candidates(load_agent_patches(), rows)
    prefer, share = cfg["repo_preference"], cfg["differs_share"]
    tier1 = pick(groups, rows, cfg["tier1_patches"], share, prefer)
    tier2 = pick(groups, rows, cfg["tier2_patches"], share, prefer, start=tier1)
    tier3 = tasks_tier(groups, rows, cfg["tier3_tasks"], prefer, start=tier2)
    out = data_path(cfg["dir"])
    for name, tier in (("tier1", tier1), ("tier2", tier2), ("tier3", tier3)):
        write_tier(out / f"swebench_{name}.json", tier, rows)
        repos = Counter(rows[p.instance_id]["repo"] for p in tier)
        n_true = sum(bool(p.differs_from_oracle) for p in tier)
        n_inst = len({p.instance_id for p in tier})
        print(f"{name}: {len(tier)} patches, {n_inst} instances (images), {n_true} differ")
        print(f"  repos: {dict(repos)}")
    print(f"candidates: {len(groups)} instances with all three agents plausible and labeled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
