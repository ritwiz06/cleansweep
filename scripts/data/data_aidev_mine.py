"""Mine AIDev review comments for removal requests, then build the taxonomy, rules and labels.

    python scripts/data/data_aidev_mine.py mine   # keyword + LLM check, check file, taxonomy, rules
    python scripts/data/data_aidev_mine.py report # the same outputs from the saved checked requests
    python scripts/data/data_aidev_mine.py labels # removal labels for the kept repositories

`mine` reads human reviewers' inline comments on .py files in the qualifying Python repos
(kept repositories first), checks at most 50 requests x 20 comments with the LLM, writes
data/processed/aidev_requests.parquet, 100 random checked results to .notes/mining_check.md for
hand labeling, and results/data_summary/aidev_taxonomy.csv and aidev_rules.csv.
`labels` maps each confirmed request in a kept repository to the code unit it is about (at
the commented commit) and writes data/processed/aidev_labels.parquet: the requested units are
label 1, the other functions and classes in the same file label 0, with FEATURE_COLUMNS. It
also records what the static detectors flag in those files (aidev_detection.parquet).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

import pandas as pd

from cleansweep.core.config import load_config
from cleansweep.data.aidev import candidates, table
from cleansweep.data.swebench import data_path
from cleansweep.mining import build_taxonomy, find_removal_requests, mine_rules

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def human_comments() -> pd.DataFrame:
    cols = ("id", "user", "user_type", "path", "body", "pull_request_url", "diff_hunk", "commit_id")
    c = table("pr_review_comments", cols)
    c = c[c.user_type == "User"].copy()
    c["repo"] = c.pull_request_url.str.extract(r"repos/([^/]+/[^/]+)/pulls")[0]
    c["pr_number"] = c.pull_request_url.str.extract(r"/pulls/(\d+)")[0].astype(int)
    return c


def mine(cfg: dict, llm) -> pd.DataFrame:
    comments = human_comments()
    qualifying = set(candidates({**cfg, "max_candidates": 10**6}).full_name)
    comments = comments[comments.repo.isin(qualifying) & comments.path.str.endswith(".py")]
    kept_path = data_path("data/splits/aidev_repos.json")
    kept = (
        {r["full_name"] for r in json.loads(kept_path.read_text())} if kept_path.exists() else set()
    )
    comments = comments.assign(kept_repo=comments.repo.isin(kept))
    comments = comments.sample(frac=1.0, random_state=0).sort_values(
        "kept_repo", ascending=False, kind="stable"
    )
    extra = load_config()["core"]["guard"].get("probe_extra_body")  # reasoning off
    checked = find_removal_requests(comments, llm, extra_body=extra)
    out = data_path("data/processed/aidev_requests.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    checked.to_parquet(out)
    print(
        f"{len(comments)} comments on .py files; {len(checked)} keyword candidates checked; "
        f"{int(checked.removal.fillna(False).sum())} removal requests"
    )
    return checked


def _text(value) -> str:
    return "-" if value is None or pd.isna(value) else str(value)


def write_check_file(checked: pd.DataFrame, n: int = 100) -> None:
    rows = checked[checked.removal.notna()].sample(
        n=min(n, int(checked.removal.notna().sum())), random_state=1
    )
    lines = [
        "# Removal-request check (for hand labeling)",
        "",
        "100 random comments the LLM checked (data/processed/aidev_requests.parquet). For each,",
        "write `yes` or `no` after **Your label** (does the reviewer ask to remove code?). Leave",
        "the LLM verdict as it is; we compare the two afterwards.",
        "",
    ]
    for i, r in enumerate(rows.itertuples(), 1):
        body = str(r.body).strip().replace("\n", "\n> ")
        lines += [
            f"## {i}. {r.repo} PR #{r.pr_number} — `{r.path}` (comment {r.id})",
            "",
            f"> {body}",
            "",
            f"- LLM: removal = {bool(r.removal)}, category = {_text(r.category)}, "
            f"target = {_text(r.target)}",
            "- **Your label:** ",
            "",
        ]
    path = Path(__file__).resolve().parents[2] / ".notes" / "mining_check.md"
    path.write_text("\n".join(lines) + "\n")
    print(f"wrote {len(rows)} comments to {path}")


def taxonomy_and_rules(checked: pd.DataFrame) -> None:
    requests = checked[checked.removal == True]  # noqa: E712 (pandas mask)
    out = data_path("results/data_summary")
    out.mkdir(parents=True, exist_ok=True)
    tax = build_taxonomy(requests)
    tax.to_csv(out / "aidev_taxonomy.csv", index=False)
    prs = table("pull_request", ("number", "agent", "merged_at", "repo_url"))
    prs = prs.assign(
        repo=prs.repo_url.str.replace(r"^https://api\.github\.com/repos/", "", regex=True)
    )
    merged = requests.merge(
        prs, left_on=["repo", "pr_number"], right_on=["repo", "number"], how="left"
    )
    items = pd.DataFrame(
        {
            **{f"agent={a}": merged.agent == a for a in merged.agent.dropna().unique()},
            **{f"category={c}": merged.category == c for c in merged.category.dropna().unique()},
            "pr merged": merged.merged_at.notna(),
            "file is a test": merged.path.str.contains(
                r"(?:^|/)tests?/|test_[^/]*\.py$|_test\.py$", regex=True
            ),
        }
    )
    rules = mine_rules(items, min_support=0.02)
    rules.to_csv(out / "aidev_rules.csv", index=False)
    print(f"taxonomy: {len(tax)} clusters (k by silhouette); rules with lift >= 1.2: {len(rules)}")


def _line_of(diff_hunk: str) -> int | None:
    """The new-file line a review comment points at (the last line of its diff hunk)."""
    lines = diff_hunk.splitlines()
    m = HUNK.match(lines[0]) if lines else None
    if not m:
        return None
    line = int(m.group(1)) - 1
    for text in lines[1:]:
        if not text.startswith("-"):
            line += 1
    return line


def _units_at(text: str) -> list[tuple[str, int, int, str]]:
    """(qualname, start, end, kind) for module-level functions/classes and their methods."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            out.append((node.name, node.lineno, node.end_lineno, kind))
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                        out.append(
                            (f"{node.name}.{sub.name}", sub.lineno, sub.end_lineno, "function")
                        )
    return out


LFS_OFF = [
    "-c",
    "filter.lfs.required=false",
    "-c",
    "filter.lfs.smudge=",
    "-c",
    "filter.lfs.process=",
]


def _ensure_clone(clone: Path, repo: str) -> bool:
    """A treeless clone (commits only; trees and files come when a commit is archived)."""
    if (clone / ".git").exists():
        return True
    clone.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{repo}.git"
    proc = subprocess.run(
        ["git", *LFS_OFF, "clone", "-q", "--filter=tree:0", "--no-checkout", url, str(clone)],
        capture_output=True,
        timeout=900,
    )
    return proc.returncode == 0


def _py_files(clone: Path, commit: str) -> int:
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit], cwd=clone, capture_output=True, text=True
    ).stdout
    return sum(line.endswith(".py") for line in out.splitlines())


def labels(
    cfg: dict, scope: str = "kept", hours: float = 1.0, max_py_files: int = 2500
) -> pd.DataFrame:
    """Label rows for the confirmed requests (see module docstring). scope "kept" uses the kept
    repositories; "requests" every qualifying repository that has a removal request (static
    analysis only: files are extracted and parsed, never run), within `hours`, skipping trees
    with more than max_py_files Python files."""
    from cleansweep.analysis import build_graph, extract_features
    from cleansweep.analysis.scope import AgentScope
    from cleansweep.core.models import FEATURE_COLUMNS
    from cleansweep.reviewer import run_detectors

    kept = {
        r["full_name"]: r for r in json.loads(data_path("data/splits/aidev_repos.json").read_text())
    }
    req = pd.read_parquet(data_path("data/processed/aidev_requests.parquet"))
    req = req[req.removal == True]  # noqa: E712
    if scope == "kept":
        req = req[req.repo.isin(kept)]
    deadline = time.time() + hours * 3600
    skipped = {"no clone": 0, "commit not reachable": 0, "too large": 0, "time": 0}
    prs = table("pull_request", ("number", "agent", "repo_url"))
    agent_of = {
        (u.replace("https://api.github.com/repos/", ""), int(n)): a
        for n, a, u in zip(prs.number, prs.agent, prs.repo_url, strict=True)
    }
    clones = data_path(cfg["clones"])
    rows, flagged = [], []
    groups = list(req.groupby(["repo", "commit_id"]))
    order = pd.Series(range(len(groups))).sample(frac=1.0, random_state=0).tolist()
    for (repo, commit), group in (groups[i] for i in order):
        if time.time() > deadline:
            skipped["time"] += 1
            continue
        clone = clones / repo.replace("/", "__")
        if not _ensure_clone(clone, repo):
            skipped["no clone"] += 1
            continue
        pr = int(group.pr_number.iloc[0])
        subprocess.run(
            ["git", *LFS_OFF, "fetch", "-q", "origin", f"pull/{pr}/head"],
            cwd=clone,
            capture_output=True,
        )
        if _py_files(clone, commit) > max_py_files:
            skipped["too large"] += 1
            continue
        with tempfile.TemporaryDirectory() as tmp:
            archive = subprocess.Popen(
                ["git", "archive", commit],
                cwd=clone,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["tar", "-xf", "-", "-C", tmp], stdin=archive.stdout, capture_output=True
            )
            if archive.wait() != 0:
                skipped["commit not reachable"] += 1
                continue
            graph = build_graph(tmp)
            paths = set(group.path)
            in_files = {u.key for u in graph.units() if u.path in paths}
            feats = extract_features(tmp, graph, units=in_files)
            # what the static detectors flag in the commented files (Reviewer detection);
            # a scope over those files keeps the per-file tools to them (vulture sees all).
            # A file is new in the pull request when its review hunk starts at "@@ -0,0".
            lines = {
                p: set(range(1, len((Path(tmp) / p).read_text(errors="replace").splitlines()) + 2))
                for p in paths
                if (Path(tmp) / p).exists()
            }
            created = {
                r.path for r in group.itertuples() if str(r.diff_hunk).startswith("@@ -0,0 ")
            }
            files_scope = AgentScope(files_added=created & set(lines), lines=lines, units=in_files)
            for item in run_detectors(tmp, graph, files_scope):
                if item.unit.path in paths and item.category not in ("format", "security"):
                    flagged.append(
                        {
                            "repo_id": f"aidev:{repo}",
                            "pr_number": pr,
                            "commit_id": commit,
                            "unit_key": item.unit.key,
                            "category": item.category,
                            "lane": item.lane,
                        }
                    )
            for path, by_path in group.groupby("path"):
                file = Path(tmp) / path
                if not file.exists():
                    continue
                units = _units_at(file.read_text(errors="replace"))
                wanted = {}
                for r in by_path.itertuples():
                    line = _line_of(str(r.diff_hunk))
                    hits = [u for u in units if line and u[1] <= line <= u[2]]
                    if hits:
                        inner = min(hits, key=lambda u: u[2] - u[1])
                        wanted[inner[0]] = r.category or "other"
                for name, *_ in units:
                    key = f"{path}::{name}"
                    row = {
                        "repo_id": f"aidev:{repo}",
                        "pr_number": pr,
                        "unit_key": key,
                        "label": int(name in wanted),
                        "category": wanted.get(name, ""),
                        "agent": agent_of.get((repo, pr), ""),
                    }
                    f = feats.loc[key] if key in feats.index else None
                    row.update(
                        {c: (float(f[c]) if f is not None else -1.0) for c in FEATURE_COLUMNS}
                    )
                    rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        from cleansweep.data.aidev import load_removal_labels

        out = load_removal_labels().iloc[0:0]
    out.to_parquet(data_path(cfg["labels"]))
    pd.DataFrame(flagged).to_parquet(data_path("data/processed/aidev_detection.parquet"))
    pos = int(out.label.sum()) if len(out) else 0
    print(f"scope {scope}: {len(groups)} commented commits; skipped {skipped}")
    print(
        f"labels: {len(out)} rows ({pos} removal requests, {len(out) - pos} other units) "
        f"from {req.groupby(['repo', 'commit_id']).ngroups} commented commits"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["mine", "report", "labels"])
    parser.add_argument("--scope", choices=["kept", "requests"], default="kept")
    parser.add_argument("--hours", type=float, default=1.0)
    args = parser.parse_args(argv)
    cfg = load_config()["data"]["aidev"]
    if args.step == "mine":
        from cleansweep.llm import get_client

        checked = mine(cfg, get_client(load_config()["core"]["llm"]))
        write_check_file(checked)
        taxonomy_and_rules(checked)
    elif args.step == "report":  # check file, taxonomy and rules from the saved requests
        checked = pd.read_parquet(data_path("data/processed/aidev_requests.parquet"))
        write_check_file(checked)
        taxonomy_and_rules(checked)
    else:
        labels(cfg, args.scope, args.hours)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
