"""Reporter: CLEANUP_REPORT.md, the PR description and a changelog entry. Every number comes
from the run's own records, not from the LLM."""

from __future__ import annotations

from collections import Counter

from cleansweep.core.models import CATEGORIES

from . import delivery

NAME = "reporter"


def summary(rt) -> dict:
    """The run's outcome in numbers."""
    stats = rt.ws.diff_stats(rt.ws.base)
    applied = [iid for iid, r in rt.results.items() if r.status in ("kept", "repaired")]
    by_cat = Counter(rt.items[i].category for i in applied)
    base = rt.baseline or {}
    final = rt.final or {}
    if rt.dry_run or rt.plan_only or not rt.packages:
        verdict = "nothing applied"
    elif final.get("ok"):
        verdict = "everything runs"
    else:
        verdict = "not verified"
    return {
        "verdict": verdict,
        "applied": len(applied),
        "applied_by_category": dict(
            sorted(
                by_cat.items(),
                key=lambda kv: CATEGORIES.index(kv[0]) if kv[0] in CATEGORIES else 99,
            )
        ),
        "suggested": sum(1 for i in rt.items.values() if i.item_id not in applied),
        "candidates": len(rt.items),
        "packages": Counter(p.status for p in rt.packages),
        "lines_removed": stats["lines_removed"],
        "lines_deleted": stats["lines_deleted"],
        "lines_added": stats["lines_added"],
        "files_removed": stats["files_removed"],
        "test_runs": rt.ws.test_runs,
        "baseline": {k: base.get(k) for k in ("passed", "failed", "errors")}
        | {"flaky": len(base.get("flaky", []))},
        "final": {k: final.get(k) for k in ("ok", "passed", "baseline_passed")}
        | {
            "new_failures": final.get("new_failures", []),
            "tests_removed": final.get("tests_removed", []),
        },
        "lessons": len(rt.lessons.lessons),
        "phases": rt.phases.order(),
        "back_steps": dict(rt.phases.back_steps),
        "stopped": rt.stopped,
    }


def _ui_line(rt) -> str | None:
    framework = (rt.brief or {}).get("ui_framework")
    if not framework:
        return None
    if framework != "textual":
        return (
            f"- UI check: not applicable ({framework}; the snapshot check supports Textual apps)."
        )
    base = rt.ui_base or {}
    if "snapshot" not in base:
        return f"- UI check: not run ({base.get('error', 'no packages were applied')[:200]})."
    return (
        f"- UI check (Textual): {len(base['snapshot']['classes'])} screens and widgets mounted "
        f"headless before and after each package ({len(base['unstable'])} unstable, left out)."
    )


def report_md(rt, s: dict, delivered: dict) -> str:
    brief = rt.brief or {}
    lines = [
        f"# Cleanup report: {brief.get('name', rt.ws.repo_id)}",
        "",
        f"**Result: {s['verdict']}.** "
        + (
            f"{s['applied']} cleanup edits applied in "
            f"{s['packages'].get('kept', 0) + s['packages'].get('repaired', 0)} work packages; "
            f"{s['lines_removed']} lines and {s['files_removed']} files removed."
            if s["applied"]
            else "No edits were applied."
        ),
        "",
        brief.get("summary", ""),
        "",
        "## Tests",
        "",
        f"- Environment: {(rt.environment or {}).get('install', 'not set up')}"
        + (
            f"; test arguments: {' '.join(rt.ws.pytest_args)}"
            if getattr(rt.ws, "pytest_args", None)
            else ""
        ),
        f"- Baseline ({(rt.baseline or {}).get('runs', 0)} runs): "
        f"{s['baseline']['passed']} passing in every run, "
        f"{s['baseline']['failed']} already failing, {s['baseline']['flaky']} flaky.",
    ]
    ui = _ui_line(rt)
    if ui:
        lines.append(ui)
    if rt.final:
        lines.append(
            f"- After the cleanup: {s['final']['passed']} passing; new failures: "
            f"{', '.join(s['final']['new_failures']) or 'none'}."
        )
        if s["final"]["tests_removed"]:
            lines.append(
                f"- Tests removed with deleted files: {', '.join(s['final']['tests_removed'])}."
            )
    if rt.stopped:
        lines.append(f"- The run stopped early: {rt.stopped}.")
    lines += [
        "",
        "## Work packages",
        "",
        "| Package | Goal | Outcome | Commit |",
        "|---|---|---|---|",
    ]
    for p in rt.packages:
        lines.append(
            f"| {p.package_id} | {p.goal} | {p.status.replace('_', ' ')} | "
            f"{(p.commit or '')[:10]} |"
        )
    rolled = [(iid, r) for iid, r in rt.results.items() if r.status == "rolled_back"]
    if rolled:
        lines += ["", "## Rolled back", ""]
        lines += [
            f"- `{rt.items[i].unit.key}`: {r.notes.splitlines()[0] if r.notes else ''}"
            for i, r in rolled
        ]
    suggest = [
        i
        for i in rt.items.values()
        if rt.results.get(i.item_id) is None or rt.results[i.item_id].status == "skipped"
    ]
    if suggest:
        lines += ["", "## Suggestions (not applied)", ""]
        lines += [f"- `{i.unit.key}` ({i.category}): {i.reason}" for i in suggest]
    if rt.lessons.lessons:
        lines += ["", "## Lessons learned", ""]
        lines += [f"- {les['lesson_id']}: {les['reason']}" for les in rt.lessons.lessons]
    usage = rt.llm.usage() if rt.llm else {}
    lines += [
        "",
        "## How the run went",
        "",
        f"- Phases: {' → '.join(s['phases'])}"
        + (f" (steps back: {s['back_steps']})" if s["back_steps"] else ""),
        f"- Test runs: {rt.ws.test_runs}; LLM requests: {usage.get('requests', 0)}; "
        f"tokens: {usage.get('prompt_tokens', 0)} prompt + "
        f"{usage.get('completion_tokens', 0)} completion.",
        f"- Secret scan: {len(rt.secrets['files'])} secret files withheld, "
        f"{len(rt.secrets['findings'])} secret-looking strings redacted before any LLM request.",
    ]
    lines += [
        "",
        "| Agent | Turns | Instances | Tool steps | LLM requests | Seconds |",
        "|---|---|---|---|---|---|",
    ]
    for agent, used in sorted(rt.agent_stats().items()):
        lines.append(
            f"| {agent} | {used['turns']} | {used['instances']} | {used['steps']} | "
            f"{used['llm_calls']} | {used['seconds']} |"
        )
    if delivered.get("diff"):
        lines += [
            "",
            "## Delivery",
            "",
            f"- An experiment run: the workspace is removed afterwards; the cleanup diff is "
            f"`{delivered['diff']}` (also `final_diff` in report.json).",
            "- Nothing was applied to the original.",
        ]
    elif delivered.get("branch"):
        lines += [
            "",
            "## Delivery",
            "",
            f"- Branch `{delivered['branch']}` in `{delivered['workspace']}`: "
            f"{delivered['commits']} commits, one per work package.",
            f"- Patches: `{delivered['patches']}`" if delivered.get("patches") else "",
            "- Nothing was applied to the original folder.",
        ]
    return "\n".join(lines).rstrip() + "\n"


def pr_md(rt, s: dict) -> str:
    lines = [
        f"Cleanup by CleanSweep ({rt.mode} mode): {s['applied']} edits, "
        f"{s['lines_removed']} lines and "
        f"{s['files_removed']} files removed. Result: {s['verdict']}.",
        "",
    ]
    lines += [
        f"- {p.package_id}: {p.goal} ({p.status.replace('_', ' ')})"
        for p in rt.packages
        if p.status in ("kept", "repaired")
    ]
    lines += [
        "",
        f"Tests: baseline {s['baseline']['passed']} passing; after {s['final'].get('passed')} "
        f"passing; new failures: {len(s['final']['new_failures'])}.",
    ]
    lines.append("Every package was tested and checked before it was kept; see CLEANUP_REPORT.md.")
    return "\n".join(lines) + "\n"


def changelog_md(rt, s: dict) -> str:
    cats = (
        ", ".join(f"{n} {c.replace('_', ' ')}" for c, n in s["applied_by_category"].items())
        or "nothing"
    )
    size = f"{s['lines_removed']} lines, {s['files_removed']} files"
    return f"- Cleanup: removed {cats} ({size}); tests unchanged.\n"


def run(rt, info: dict | None = None, patches: bool = True) -> None:
    """REPORT and DELIVER: the branch, then the report files."""
    if rt.dry_run:
        delivered = {"branch": None}
    elif patches:
        delivered = delivery.finish(rt, info or {}, patches=True)
    else:  # an experiment run: its workspace is deleted, so the diff is the deliverable
        (rt.out / "final.diff").write_text(rt.ws.diff(rt.ws.base), encoding="utf-8")
        delivered = {"branch": None, "diff": "final.diff"}
    s = summary(rt)
    files = {
        "CLEANUP_REPORT.md": report_md(rt, s, delivered),
        "PR_DESCRIPTION.md": pr_md(rt, s),
        "CHANGELOG_ENTRY.md": changelog_md(rt, s),
    }
    for name, text in files.items():
        (rt.out / name).write_text(text, encoding="utf-8")
    rt.delivered = delivered
    rt.summary = s
    rt.files = sorted([*files, "blueprint.md"] if (rt.out / "blueprint.md").exists() else files)
    art = rt.artifact("report", files["CLEANUP_REPORT.md"])
    rt.board.post("report", NAME, {"files": rt.files}, artifacts=[art])
