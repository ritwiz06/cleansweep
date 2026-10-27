"""AIDev-pop: Python repositories with agent pull requests, their histories and labels.

Tables come from the hao-li/AIDev dataset (repository, pull_request, pr_review_comments,
pr_commits parquet files in data/raw/aidev). Repositories run only in Docker
(cleansweep.sandbox.aidev_docker); this module only reads tables and git metadata.
"""

from __future__ import annotations

import json
import re
import subprocess
from functools import lru_cache

import pandas as pd

from cleansweep.core.config import load_config
from cleansweep.core.models import CommitEvent, RepoRef

from .swebench import data_path

PR_REF = re.compile(r"\(#(\d+)\)\s*$|Merge pull request #(\d+)", re.MULTILINE)


def _cfg() -> dict:
    return load_config()["data"]["aidev"]


def full_name(repo_url: str) -> str:
    """owner/name from an API or web URL."""
    return re.sub(r"^https://(api\.)?github\.com/(repos/)?", "", repo_url).rstrip("/")


@lru_cache(maxsize=4)
def table(name: str, columns: tuple[str, ...] | None = None) -> pd.DataFrame:
    path = data_path(_cfg()["dir"]) / f"{name}.parquet"
    return pd.read_parquet(path, columns=list(columns) if columns else None)


def candidates(cfg: dict | None = None) -> pd.DataFrame:
    """Python, non-fork repositories with at least min_agent_prs merged agent pull requests:
    a seeded random sample of at most max_candidates."""
    cfg = cfg or _cfg()
    repos = table("repository")
    prs = table("pull_request", ("id", "agent", "merged_at", "repo_id"))
    merged = prs[prs.merged_at.notna()].groupby("repo_id").size().rename("merged_agent_prs")
    py = repos[(repos.language == "Python") & (~repos.is_forked)].merge(
        merged, left_on="id", right_index=True
    )
    qualifying = py[py.merged_agent_prs >= int(cfg["min_agent_prs"])]
    n = min(int(cfg["max_candidates"]), len(qualifying))
    picked = qualifying.sample(n=n, random_state=int(cfg["seed"])).sort_values("full_name")
    picked = picked.assign(clone_url="https://github.com/" + picked.full_name + ".git")
    return picked[["id", "full_name", "clone_url", "stars", "merged_agent_prs"]].reset_index(
        drop=True
    )


def load_repos(min_agent_prs: int = 10) -> list[RepoRef]:
    """The kept (runnable) repositories from data/splits/aidev_repos.json."""
    path = data_path("data/splits/aidev_repos.json")
    if not path.exists():
        return []
    clones = data_path(_cfg()["clones"])
    out = []
    for r in json.loads(path.read_text()):
        if r["merged_agent_prs"] < min_agent_prs:
            continue
        out.append(
            RepoRef(
                repo_id=f"aidev:{r['full_name']}",
                url=r["clone_url"],
                local_path=str(clones / r["full_name"].replace("/", "__")),
                head_sha=r["head_sha"],
                test_cmd="python -m pytest",
            )
        )
    return out


def _git(clone: str, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=clone, capture_output=True, text=True).stdout


def _agent_prs(name: str) -> tuple[dict[int, str], dict[str, int]]:
    """For one repository: agent PR number -> agent, and PR commit sha -> PR number."""
    prs = table("pull_request", ("id", "number", "agent", "repo_url"))
    mine = prs[prs.repo_url.map(full_name) == name]
    by_number = dict(zip(mine.number.astype(int), mine.agent, strict=True))
    commits = table("pr_commits", ("sha", "pr_id"))
    ids = dict(zip(mine.id, mine.number.astype(int), strict=True))
    shas = commits[commits.pr_id.isin(ids)]
    return by_number, {s: ids[p] for s, p in zip(shas.sha, shas.pr_id, strict=True)}


def load_history(repo: RepoRef) -> list[CommitEvent]:
    """The last history_commits first-parent commits, oldest first, marked with the agent pull
    request they came from (by commit sha or a "(#N)" / "Merge pull request #N" reference)."""
    cfg = _cfg()
    name = repo.repo_id.removeprefix("aidev:")
    cache = data_path(cfg["history_cache"]) / f"{name.replace('/', '__')}.json"
    if cache.exists():
        return [CommitEvent(**e) for e in json.loads(cache.read_text())]
    clone = repo.local_path or str(data_path(cfg["clones"]) / name.replace("/", "__"))
    head = repo.head_sha or "HEAD"
    log = _git(
        clone,
        "log",
        "--first-parent",
        "-n",
        str(cfg["history_commits"]),
        "--format=%H%x1f%cI%x1f%B%x1e",
        head,
    )
    by_number, by_sha = _agent_prs(name)
    events = []
    for record in log.split("\x1e"):
        parts = record.strip("\n").split("\x1f")
        if len(parts) < 3:
            continue
        sha, when, message = parts[0].strip(), parts[1], parts[2]
        number = by_sha.get(sha)
        if number is None:
            m = PR_REF.search(message)
            number = int(m.group(1) or m.group(2)) if m else None
        agent = by_number.get(number) if number is not None else None
        files = _git(clone, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).split()
        events.append(
            CommitEvent(
                sha=sha,
                timestamp=pd.Timestamp(when).tz_convert("UTC").isoformat(),
                is_agent=agent is not None,
                agent=agent,
                pr_number=number,
                files=files,
            )
        )
    events.reverse()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([e.__dict__ for e in events]))
    return events


def load_removal_labels() -> pd.DataFrame:
    """Labeled units from mined review comments (scripts/data_aidev_mine.py), kept repos only."""
    path = data_path(_cfg()["labels"])
    if not path.exists():
        from cleansweep.core.models import FEATURE_COLUMNS

        cols = ["repo_id", "pr_number", "unit_key", "label", "category", "agent", *FEATURE_COLUMNS]
        return pd.DataFrame(columns=cols)
    return pd.read_parquet(path)
