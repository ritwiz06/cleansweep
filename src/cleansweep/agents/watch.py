"""Watch mode: follow a repository's commits, estimate its slop with the static detectors, decide
when to clean (with the reason), and clean a scratch copy when it does.

    cleansweep watch <repo> --budget-tests N [--interval S] [--once] [--out DIR]

The original repository is never written to: a clean runs on a copy of the commit (git archive),
capped at the test runs left in the budget, and delivers its branch and CLEANUP_REPORT.md in the
watch folder. Every poll appends one line
to OUT/watch_log.jsonl: the commit, the slop open (items, lines and their share of the Python
lines, by category), the decision ("clean" or "wait"), its reason, and the clean's outcome.
OUT/watch_state.json keeps the last commit seen, the test runs used and the items already
delivered by a clean (awaiting a merge), so a watch can stop and resume.

The decision rule (decide) is the same for a live watch and for simulate_watch, which replays a
recorded history quickly from the cached slop measurements of the v1 Scheduler replay.
"""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

THRESHOLD = 0.02  # slop lines over Python lines, as v1's adaptive policy
NEW_ITEMS = 3  # new slop items since the last clean that are worth a clean on their own
MAX_GAP = 20  # commits without a clean while slop is open
BASELINE_RUNS = 3
MAX_PACKAGE = 4


def clean_cost(
    items: int, baseline_runs: int = BASELINE_RUNS, max_package: int = MAX_PACKAGE
) -> int:
    """Test runs a clean of this many items needs: the baseline, one per package, the final."""
    return baseline_runs + math.ceil(items / max_package) + 1


def affordable(items: int, left: int, baseline_runs: int = BASELINE_RUNS) -> int:
    """Items a clean can take on with `left` test runs (the baseline, one run per package, the
    final suite)."""
    return max(0, min(items, (left - baseline_runs - 1) * MAX_PACKAGE))


def decide(state: dict) -> tuple[str, str]:
    """("clean" or "wait", the reason) for the slop open at a commit and the budget left. With a
    test budget that can't pay for every open item, the clean takes on what it can."""
    items, loc = state["open_items"], max(state.get("loc", 0), 1)
    if not items:
        return "wait", "no slop is open"
    share = state["slop_loc"] / loc
    baseline = state.get("baseline_runs", BASELINE_RUNS)
    budget = state.get("budget_tests") or 0
    left = budget - state.get("test_runs_used", 0)
    can = affordable(items, left, baseline) if budget else items
    if can == 0:
        return "wait", (
            f"the test budget is used up: a clean needs at least {baseline + 2} test runs and "
            f"{left} of {budget} are left"
        )
    part = f"; the budget left covers {can} of the {items} items" if can < items else ""
    if share >= THRESHOLD:
        return "clean", (
            f"slop is {share:.1%} of the Python lines, over the {THRESHOLD:.0%} threshold{part}"
        )
    if state.get("new_items", 0) >= NEW_ITEMS:
        return (
            "clean",
            f"the commits since the last clean added {state['new_items']} slop items{part}",
        )
    if state.get("commits_since_clean", 0) >= MAX_GAP:
        return "clean", (
            f"{state['commits_since_clean']} commits since the last clean, with {items} slop items "
            f"open{part}"
        )
    return "wait", (
        f"slop is {share:.1%} of the Python lines (threshold {THRESHOLD:.0%}), {items} items open, "
        f"{state.get('new_items', 0)} new, {state.get('commits_since_clean', 0)} commits since the "
        "last clean"
    )


def _open(measured: dict, delivered: set[str]) -> dict:
    return {k: v for k, v in measured["items"].items() if k not in delivered}


def _slop(open_items: dict, loc: int) -> dict:
    lines = sum(v[2] for v in open_items.values())
    return {
        "items": len(open_items),
        "loc": lines,
        "share": round(lines / max(loc, 1), 4),
        "by_category": dict(Counter(v[0] for v in open_items.values())),
    }


def simulate_watch(history, repo_dir: str, budget_tests: int, cfg: dict | None = None) -> dict:
    """Replay a history under the watch rule, from the v1 replay's slop measurements. A clean
    removes the open items (as in v1's replay) and costs clean_cost test runs."""
    from cleansweep.scheduler.replay import snapshots

    snaps = snapshots(history, repo_dir, cfg)
    if not snaps:
        return {"policy": "watch", "commits": 0}
    removed: set[str] = set()
    seen: set[str] = set()
    current = snaps[min(snaps)]
    used = cleans = debt = since = 0
    decisions = []
    for i, commit in enumerate(history):
        if i in snaps:
            current = snaps[i]
        since += 1
        open_items = _open(current, removed)
        new = len(set(open_items) - seen)
        seen |= set(open_items)
        state = {
            "open_items": len(open_items),
            "slop_loc": sum(v[2] for v in open_items.values()),
            "loc": current["loc"],
            "new_items": new,
            "commits_since_clean": since,
            "test_runs_used": used,
            "budget_tests": budget_tests,
        }
        decision, reason = decide(state)
        if decision == "clean":
            take = sorted(open_items)
            if budget_tests:
                take = take[: affordable(len(take), budget_tests - used)]
            cleans += 1
            used += clean_cost(len(take))
            removed |= set(take)
            open_items = {k: v for k, v in open_items.items() if k not in removed}
            since, seen = 0, set(open_items)
        debt += len(open_items)
        decisions.append({"index": i, "sha": commit.sha, "decision": decision, "reason": reason})
    return {
        "policy": "watch",
        "commits": len(history),
        "measured_commits": len(snaps),
        "sweeps": cleans,
        "test_runs_est": used,
        "slop_debt": debt,
        "slop_debt_per_commit": round(debt / len(history), 3),
        "final_slop": len(_open(current, removed)),
        "removed": len(removed),
        "decisions": decisions,
    }


def _git(repo: str, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return out.stdout.strip()


class Watch:
    """A watch over one repository, its state and log in an output folder."""

    def __init__(self, repo: str, out: str, budget_tests: int = 0, cfg: dict | None = None):
        self.repo = str(Path(repo).expanduser().resolve())
        self.out = Path(out).expanduser().resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.budget_tests = budget_tests
        self.cfg = cfg
        self.state_path = self.out / "watch_state.json"
        self.state = (
            json.loads(self.state_path.read_text())
            if self.state_path.exists()
            else {
                "last": None,
                "test_runs_used": 0,
                "delivered": [],
                "commits_since_clean": 0,
                "seen": [],
                "cleans": 0,
                "polls": 0,
            }
        )

    def log(self, entry: dict) -> dict:
        entry = {"t": datetime.now(UTC).isoformat(timespec="seconds"), **entry}
        with (self.out / "watch_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        self.state_path.write_text(json.dumps(self.state, indent=1))
        return entry

    def poll(self, clean: Callable[[str, str, int | None], dict] | None = None) -> dict | None:
        """Look at the newest commit once; decide; clean when the rule says so. None when there
        is no new commit."""
        from cleansweep.scheduler.replay import measure

        if not (Path(self.repo) / ".git").exists():
            raise ValueError(f"{self.repo} is not a git repository")
        head = _git(self.repo, "rev-parse", "HEAD")
        if head == self.state["last"]:
            return None
        commits = (
            _git(self.repo, "rev-list", "--first-parent", f"{self.state['last']}..{head}").split()
            if self.state["last"]
            else [head]
        )
        self.state["commits_since_clean"] += len(commits)
        self.state["polls"] += 1
        measured = measure(self.repo, head)
        open_items = _open(measured, set(self.state["delivered"]))
        new = sorted(set(open_items) - set(self.state["seen"]))
        self.state["seen"] = sorted(set(self.state["seen"]) | set(open_items))
        slop = _slop(open_items, measured["loc"])
        decision, reason = decide(
            {
                "open_items": slop["items"],
                "slop_loc": slop["loc"],
                "loc": measured["loc"],
                "new_items": len(new),
                "commits_since_clean": self.state["commits_since_clean"],
                "test_runs_used": self.state["test_runs_used"],
                "budget_tests": self.budget_tests,
            }
        )
        self.state["last"] = head
        entry = {
            "commit": head,
            "subject": _git(self.repo, "log", "-1", "--format=%s", head),
            "new_commits": len(commits),
            "commits_since_clean": self.state["commits_since_clean"],
            "slop": slop,
            "new_items": len(new),
            "decision": decision,
            "reason": reason,
            "run": None,
            "outcome": None,
            "test_runs_used": self.state["test_runs_used"],
            "budget_tests": self.budget_tests,
        }
        if decision == "clean" and clean is not None:
            self.state["cleans"] += 1
            run = self.out / f"clean-{self.state['cleans']:03d}"
            with tempfile.TemporaryDirectory() as tmp:
                snapshot = Path(tmp) / Path(self.repo).name
                snapshot.mkdir()
                archive = subprocess.Popen(
                    ["git", "archive", head], cwd=self.repo, stdout=subprocess.PIPE
                )
                subprocess.run(
                    ["tar", "-xf", "-", "-C", str(snapshot)], stdin=archive.stdout, check=True
                )
                archive.wait()
                left = (
                    self.budget_tests - self.state["test_runs_used"] if self.budget_tests else None
                )
                result = clean(str(snapshot), str(run), left)
            summary = result.get("summary", {})
            runs = result["report"].stats.get("test_runs", 0)
            self.state["test_runs_used"] += runs
            self.state["delivered"] = sorted(set(self.state["delivered"]) | set(open_items))
            self.state["commits_since_clean"] = 0
            self.state["seen"] = []
            entry.update(
                run=run.name,
                outcome={
                    "verdict": summary.get("verdict"),
                    "applied": summary.get("applied", 0),
                    "lines_removed": summary.get("lines_removed", 0),
                    "test_runs": runs,
                },
                test_runs_used=self.state["test_runs_used"],
            )
        return self.log(entry)

    def run(
        self,
        clean: Callable[[str, str, int | None], dict] | None,
        interval: float = 60,
        polls: int | None = None,
        on_entry: Callable[[dict], None] | None = None,
    ) -> None:
        """Poll every `interval` seconds until stopped (Ctrl-C), or `polls` times."""
        done = 0
        while polls is None or done < polls:
            entry = self.poll(clean)
            if entry is not None and on_entry is not None:
                on_entry(entry)
            done += 1
            if polls is None or done < polls:
                time.sleep(interval)
