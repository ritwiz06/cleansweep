"""Planner: turns the safe items into work packages ordered by risk and dependencies, each with
a goal, files, edits, a verification plan and a rollback plan, and writes blueprint.md."""

from __future__ import annotations

from collections import defaultdict

from cleansweep.core.io import to_dict
from cleansweep.core.models import CATEGORIES, CleanupItem
from cleansweep.scheduler.batching import risk_tier

from .runtime import Package
from .tools import related_tests

NAME = "planner"
WORDS = {
    "leftover_file": ("leftover file", "leftover files"),
    "dead_code": ("unused function or class", "unused functions and classes"),
    "duplicate": ("duplicate", "duplicates"),
    "wrapper": ("one-use wrapper", "one-use wrappers"),
    "unused_import": ("unused import", "unused imports"),
    "unused_dependency": ("unused dependency", "unused dependencies"),
    "format": ("formatting change", "formatting changes"),
    "unused_variable": ("unused local variable", "unused local variables"),
    "debug_leftover": ("debug leftover", "debug leftovers"),
    "commented_code": ("block of commented-out code", "blocks of commented-out code"),
    "todo_note": ("leftover note", "leftover notes"),
    "redundant_check": ("redundant check", "redundant checks"),
}
AST_SAME = {"format", "commented_code", "todo_note"}  # proven by AST equality
# line-level edits: comment-only ones keep the AST (tier 0); the others change code
LINE_TIERS = {
    "commented_code": 0,
    "todo_note": 0,
    "unused_variable": 1,
    "debug_leftover": 1,
    "redundant_check": 2,
}


def tier(item: CleanupItem) -> int:
    return LINE_TIERS.get(item.category, risk_tier(item))


def goal(items: list[CleanupItem]) -> str:
    """One sentence a person can read, e.g. "Remove 2 unused imports in shopcart/cart.py"."""
    cats = sorted({i.category for i in items}, key=CATEGORIES.index)
    files = sorted({i.unit.path for i in items})
    what = []
    for c in cats:
        n = sum(i.category == c for i in items)
        one, many = WORDS.get(c, (c.replace("_", " "), c.replace("_", " ") + " items"))
        what.append(f"{n} {one if n == 1 else many}")
    verb = "Reformat" if cats == ["format"] else "Remove"
    where = files[0] if len(files) == 1 else f"{len(files)} files"
    return f"{verb} {' and '.join(what)} in {where}"


def _depends(graph, earlier: list[CleanupItem], later: list[CleanupItem]) -> bool:
    """A later package depends on an earlier one when it removes code that the earlier
    package's removed code uses: if the earlier one is rolled back, the later edit breaks it."""
    removed = {i.unit.key for i in earlier}
    return any(c in removed for i in later for c in graph.callers(i.unit.key))


def make_packages(rt, items: list[CleanupItem], start: int = 1) -> list[Package]:
    """Group items by risk tier and file (format changes last, in their own package)."""
    size = max(1, int(rt.acfg.get("max_package", 4)))
    groups: dict[tuple, list[CleanupItem]] = defaultdict(list)
    for item in items:
        key = (9, "format", "") if item.category == "format" else (tier(item), item.unit.path, "")
        groups[key].append(item)
    packages: list[Package] = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda i: (CATEGORIES.index(i.category), i.unit.key))
        for k in range(0, len(group), size):
            chunk = group[k : k + size]
            pid = f"P{start + len(packages)}"
            files = sorted({i.unit.path for i in chunk})
            checks = ["compile", "tests"]
            if all(i.category in AST_SAME for i in chunk):
                checks.append("ast")
            else:
                checks.append("probes")
            if any(i.action == "remove_dependency" for i in chunk):
                checks.append("dependency")
            if any(i.action in ("delete_unit", "delete_file") for i in chunk):
                checks.append("public_api")
            if (rt.brief or {}).get("ui_framework"):
                checks.append("ui")
            pkg = Package(
                package_id=pid,
                goal=goal(chunk),
                items=[i.item_id for i in chunk],
                files=files,
                risk=key[0],
                verify={
                    "related_tests": related_tests(rt.graph, files),
                    "checks": checks,
                    "probe_targets": [i.unit.key for i in chunk if i.unit.kind == "function"],
                },
                rollback=f"reset the workspace to the checkpoint before {pid}; "
                "later packages are unaffected",
            )
            pkg.depends_on = [
                p.package_id
                for p in packages
                if _depends(rt.graph, [rt.items[i] for i in p.items], chunk)
            ]
            packages.append(pkg)
    return packages


def blueprint(rt, packages: list[Package]) -> str:
    """The plan as Markdown, for people and for the development squad."""
    brief = rt.brief or {}
    suggest = [i for i in rt.items.values() if i.lane != "safe" or i.action == "report_only"]
    lines = [
        f"# Cleanup blueprint: {brief.get('name', rt.ws.repo_id)}",
        "",
        brief.get("summary", ""),
        "",
        f"Mode: {rt.mode}. {len(packages)} work packages, applied one at a time; "
        "each is tested and "
        "checked, then kept as one commit, repaired, or rolled back.",
        "",
    ]
    for p in packages:
        lines += [
            f"## {p.package_id}: {p.goal}" + (f" ({p.status})" if p.status != "planned" else ""),
            "",
            f"- Risk tier: {p.risk}"
            + (f"; depends on {', '.join(p.depends_on)}" if p.depends_on else ""),
            f"- Files: {', '.join(p.files)}",
            "- Edits:",
        ]
        for iid in p.items:
            item = rt.items[iid]
            lines.append(f"  - {item.action} `{item.unit.key}` ({item.category}): {item.reason}")
        tests = p.verify.get("related_tests") or ["the full suite"]
        lines += [
            f"- Verify: {', '.join(p.verify.get('checks', []))}; related tests: {', '.join(tests)}",
            f"- Rollback: {p.rollback}",
            "",
        ]
    if suggest:
        lines += ["## Suggestions (not applied)", ""]
        lines += [f"- `{i.unit.key}` ({i.category}): {i.reason}" for i in suggest]
        lines.append("")
    return "\n".join(lines)


def replan(rt) -> list[Package]:
    """After a rollback: items a new lesson fits, or that build on a rolled-back package, go to
    the suggest lane; the remaining safe items are packaged again."""
    done = rt.packages[: rt.current]
    rolled = {p.package_id for p in done if p.status == "rolled_back"}
    remaining = [i for p in rt.packages[rt.current :] for i in p.items]
    deps = {i for p in rt.packages[rt.current :] if set(p.depends_on) & rolled for i in p.items}
    keep = []
    for iid in remaining:
        item = rt.items[iid]
        framework = rt.graph.framework_callback(item.unit.key) if item.unit.name else None
        lessons = rt.lessons.matching(item, framework) if rt.ablation != "no_lessons" else []
        if lessons:
            item.lane = "suggest"
            item.reason = (
                f"Planner: lesson {lessons[0]['lesson_id']} fits this edit: {lessons[0]['reason']}"
            )
            item.evidence.append(f"lesson {lessons[0]['lesson_id']}")
            rt.log.emit(
                "decision",
                agent=NAME,
                payload={
                    "item_id": iid,
                    "lane": "suggest",
                    "lessons_cited": [lessons[0]["lesson_id"]],
                },
            )
        elif iid in deps:
            item.lane = "suggest"
            item.reason = "Planner: it builds on a package that was rolled back."
            rt.log.emit(
                "decision",
                agent=NAME,
                payload={"item_id": iid, "lane": "suggest", "reason": item.reason},
            )
        else:
            keep.append(item)
    return done + make_packages(rt, keep, start=len(done) + 1)


def run(rt) -> None:
    """PLAN: packages and blueprint.md, sent to the development squad."""
    budget = rt.budget(NAME)
    packages = replan(rt) if rt.packages else make_packages(rt, rt.safe_items())
    rt.packages = packages
    rt.planned = True
    text = blueprint(rt, packages)
    (rt.out / "blueprint.md").write_text(text, encoding="utf-8")
    art = rt.artifact("blueprint", text)
    rt.board.post(
        "blueprint", NAME, {"packages": [p.package_id for p in packages]}, artifacts=[art]
    )
    rt.record_usage(NAME, budget)
    items = list(rt.items.values())
    rt.log.v1("plan", {"items": to_dict(items), "seconds": 0.0})
    rt.log.v1("rank", {"skipped": True, "seconds": 0.0})
    rt.log.v1(
        "batch",
        {
            "max_size": int(rt.acfg.get("max_package", 4)),
            "batches": [p.items for p in packages],
            "seconds": 0.0,
        },
    )
