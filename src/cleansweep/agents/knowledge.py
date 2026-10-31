"""Slop knowledge base: v1's mined results as a tool the agents can query.

Sources: association rules (agent / change → slop category), the review-comment taxonomy with
each cluster's mapped category, and the framework conventions table."""

from __future__ import annotations

import csv
import fnmatch
from pathlib import Path

from cleansweep.analysis.frameworks import FRAMEWORKS
from cleansweep.core.config import REPO_ROOT

SUMMARY = REPO_ROOT / "results" / "data_summary"
TOP = 5


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


class KnowledgeBase:
    """Rules, taxonomy clusters and framework conventions, queried by category and filters."""

    def __init__(self, folder: str | Path | None = None):
        folder = Path(folder) if folder else SUMMARY
        self.rules = _rows(folder / "aidev_rules.csv")
        self.clusters = [
            r for r in _rows(folder / "detection_by_category.csv") if r.get("level") == "cluster"
        ]
        self.total_requests = sum(int(r.get("requests") or 0) for r in self.clusters)

    def rules_for(
        self, category: str, agent: str = "", test_file: bool | None = None
    ) -> list[dict]:
        """Rules that mention the category (and the agent, and test files, when given)."""
        out = []
        for r in self.rules:
            items = set(r["antecedents"].split(", ")) | set(r["consequents"].split(", "))
            if f"category={category}" not in items:
                continue
            if agent and not any(
                i.startswith("agent=") and agent.lower() in i.lower() for i in items
            ):
                continue
            if test_file is not None and ("file is a test" in items) != test_file:
                continue
            out.append(r)
        return sorted(out, key=lambda r: -float(r["lift"]))

    def clusters_for(self, category: str) -> list[dict]:
        """Review-comment clusters whose requests map to the category, largest first."""
        found = [c for c in self.clusters if c.get("mapped_category") == category]
        return sorted(found, key=lambda c: -int(c.get("requests") or 0))

    def prior(self, category: str) -> float | None:
        """Share of the mined removal requests that map to the category."""
        if not self.total_requests:
            return None
        n = sum(int(c.get("requests") or 0) for c in self.clusters_for(category))
        return round(n / self.total_requests, 3)

    def query(
        self, category: str, framework: str = "", agent: str = "", file_pattern: str = ""
    ) -> str:
        """A short text answer for an agent."""
        test_file = None
        if file_pattern:
            test_file = any(
                fnmatch.fnmatch(file_pattern, p)
                for p in ("test_*", "*_test.py", "tests/*", "*/tests/*")
            )
        lines = []
        prior = self.prior(category)
        if prior:
            lines.append(
                f"{prior:.0%} of {self.total_requests} mined maintainer removal requests "
                f"map to {category}"
            )
        for r in self.rules_for(category, agent, test_file)[:TOP]:
            lines.append(
                f"rule: {r['antecedents']} -> {r['consequents']} "
                f"(confidence {float(r['confidence']):.2f}, lift {float(r['lift']):.2f})"
            )
        for c in self.clusters_for(category)[:3]:
            lines.append(
                f"review cluster {c['cluster']} ({c['requests']} requests): {c['top_terms']}"
            )
        if framework:
            conv = FRAMEWORKS.get(framework.lower())
            if conv:
                lines.append(
                    f"{framework} calls these methods by name: {sorted(conv['names'])[:12]}, "
                    f"and any method starting with {list(conv['prefixes'])}"
                )
            else:
                lines.append(f"no conventions recorded for {framework}")
        return "\n".join(lines) or f"nothing mined about {category}"
