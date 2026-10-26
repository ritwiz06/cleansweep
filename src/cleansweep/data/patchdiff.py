"""PatchDiff: plausible agent patches for SWE-bench Verified, with behavior labels and tests.

Patches come from the three SWE-bench submissions PatchDiff studied (in its GitHub repo).
Labels and generated tests come from the paper's results archive (Zenodo):
`results/RQ2_<agent>_difftests.json` maps each instance to the test files PatchDiff generated,
each with the tests that behaved differently from the developer's fix. A patch with any such
test is `differs_from_oracle=True` (260 of the 724 patches PatchDiff tested); a tested patch
without one is False; a plausible patch PatchDiff didn't test is None.
"""

from __future__ import annotations

import json
from pathlib import Path

from cleansweep.core.config import REPO_ROOT, load_config
from cleansweep.core.models import AgentPatch

from .swebench import data_path


def _cfg() -> dict:
    return load_config()["data"]["patchdiff"]


def results_dir(cfg: dict) -> Path:
    root = data_path(cfg["results_dir"])
    found = sorted(root.glob("**/results/RQ2_*_difftests.json"))
    if not found:
        raise FileNotFoundError(
            f"no PatchDiff results under {root}; run scripts/data_fetch_patchdiff.py"
        )
    return found[0].parent


def plausible_patches(cfg: dict) -> dict[tuple[str, str], str]:
    """(agent, instance_id) -> patch text, for patches the submission marks as resolved."""
    root = data_path(cfg["dir"]) / "data" / "tool_results"
    patches = {}
    for agent, pattern in cfg["agents"].items():
        found = sorted(root.glob(pattern))
        if len(found) != 1:
            raise FileNotFoundError(f"expected one submission folder for {agent} ({pattern})")
        folder = found[0]
        resolved = set(json.loads((root / folder / "results.json").read_text())["resolved"])
        for line in (root / folder / "all_preds.jsonl").read_text().splitlines():
            pred = json.loads(line)
            if pred["instance_id"] in resolved and pred.get("model_patch"):
                patches[(agent, pred["instance_id"])] = pred["model_patch"]
    return patches


def build_index(cfg: dict | None = None) -> dict:
    """Write each patch's hidden tests to tests_dir and return the label/test index."""
    cfg = cfg or _cfg()
    results = results_dir(cfg)
    tests_root = data_path(cfg["tests_dir"])
    keep = int(cfg.get("max_hidden_tests", 10))
    index: dict[str, dict] = {}
    for agent in cfg["agents"]:
        tested = json.loads((results / f"RQ2_{agent}_difftests.json").read_text())
        runall = json.loads((results / f"RQ1_{agent}_runall.json").read_text())
        for instance_id, generated in tested.items():
            revealing = [g for g in generated if g.get("differential_tests")]
            others = [g for g in generated if not g.get("differential_tests")]
            paths = []
            for g in (revealing + others)[:keep]:
                path = tests_root / agent / instance_id / f"test_patchdiff_{g['idx']}.py"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(g["gen_test_file"], encoding="utf-8")
                paths.append(_relative(path))
            index[f"{agent}/{instance_id}"] = {
                "differs_from_oracle": bool(revealing),
                "n_revealing_tests": len(revealing),
                "runall_differs": instance_id in runall,
                "hidden_tests": paths,
            }
        for instance_id in runall:
            index.setdefault(
                f"{agent}/{instance_id}",
                {
                    "differs_from_oracle": None,
                    "n_revealing_tests": 0,
                    "runall_differs": True,
                    "hidden_tests": [],
                },
            )
    out = data_path(cfg["index"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, indent=1, sort_keys=True), encoding="utf-8")
    return index


def _relative(path: Path) -> str:
    """Repo-relative when inside the repository, else absolute."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def load_index(cfg: dict | None = None) -> dict:
    cfg = cfg or _cfg()
    path = data_path(cfg["index"])
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; run scripts/data_fetch_patchdiff.py")
    return json.loads(path.read_text(encoding="utf-8"))


def load_agent_patches(agents: list[str] | None = None) -> list[AgentPatch]:
    """The plausible patches of PatchDiff's three agents (877), with labels and hidden tests."""
    cfg = _cfg()
    index = load_index(cfg)
    out = []
    for (agent, instance_id), patch in sorted(plausible_patches(cfg).items()):
        if agents is not None and agent not in agents:
            continue
        entry = index.get(f"{agent}/{instance_id}", {})
        out.append(
            AgentPatch(
                instance_id=instance_id,
                agent=agent,
                patch=patch,
                differs_from_oracle=entry.get("differs_from_oracle"),
                hidden_tests=list(entry.get("hidden_tests", [])),
            )
        )
    return out
