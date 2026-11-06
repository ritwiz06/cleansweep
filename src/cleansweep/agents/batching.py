"""Investigation batching (core.agents.investigate_batch: on).

Candidates with the same pattern (the same detector and edit, lane and kind of evidence) share
one Investigator request, at most MAX_BATCH at a time, and a cautious verdict is reused for a
later candidate with an identical pattern within the run. Every candidate still gets its own
verdict, checked like a single investigation's; a missing or rule-breaking verdict sends that
candidate to the single-candidate investigation, so batching never makes a decision riskier."""

from __future__ import annotations

import concurrent.futures as cf

import jsonschema

from cleansweep.core.models import CleanupItem

from .investigator import (
    FINAL_SCHEMA,
    NAME,
    _checker,
    _framework,
    first_checks,
    task_text,
    uncertain,
)
from .lessons import pattern_for
from .protocol import load_prompt, react

MAX_BATCH = 5
BATCH_SCHEMA = {
    "type": "object",
    "required": ["verdicts"],
    "properties": {"verdicts": {"type": "array", "items": {"type": "object"}}},
}
REUSABLE = {"suggest", "drop"}  # a reused "safe" would apply an edit without its own evidence


def batch_on(acfg: dict) -> bool:
    """core.agents.investigate_batch as a bool (YAML reads bare on/off as booleans)."""
    value = acfg.get("investigate_batch", "off")
    value = {True: "on", False: "off"}.get(value, value)
    if value not in ("on", "off"):
        raise ValueError(f"investigate_batch must be on or off, got {value!r}")
    return value == "on"


def pattern_key(rt, item: CleanupItem) -> tuple:
    """Candidates with the same key share a request: the same detector (category and edit), the
    same lane and the same kind of evidence (why they are uncertain, the framework)."""
    why = uncertain(rt, item) or ""
    return (item.category, item.action, item.lane, why, _framework(rt, item) or "")


def reuse_key(rt, item: CleanupItem) -> tuple:
    """An identical pattern: the batching key plus the lesson pattern (unit kind, name pattern,
    folder), so a verdict on one on_* method of a Textual screen fits its siblings."""
    pattern = pattern_for(item, _framework(rt, item))
    return pattern_key(rt, item) + tuple(sorted(pattern.items()))


def investigate_batched(rt, asked: list[tuple[int, CleanupItem]], single) -> None:
    """Verdicts for the candidates the Investigators get, in rt.verdicts. single(rt, item, n) is
    the one-candidate investigation, for fallbacks and for candidates the Manager sent back."""
    alone = [(n, i) for n, i in asked if i.item_id in rt.retry]
    first, later, keys = [], [], set()
    for n, item in asked:
        if item.item_id in rt.retry or _reuse(rt, item):
            continue
        key = reuse_key(rt, item)
        (later if key in keys else first).append((n, item))
        keys.add(key)
    _ask(rt, first, single, alone)
    # the second round: what the first round's cautious verdicts don't already settle
    _ask(rt, [(n, i) for n, i in later if not _reuse(rt, i)], single, [])


def batches(rt, jobs: list[tuple[int, CleanupItem]]) -> list[list[tuple[int, CleanupItem]]]:
    """Jobs grouped by pattern_key, in their order, at most MAX_BATCH per group."""
    groups: dict[tuple, list] = {}
    for job in jobs:
        groups.setdefault(pattern_key(rt, job[1]), []).append(job)
    return [g[i : i + MAX_BATCH] for g in groups.values() for i in range(0, len(g), MAX_BATCH)]


def _ask(rt, jobs, single, alone) -> None:
    """Groups of two or more as batches, the rest (and the batches' fallbacks) one by one."""
    groups = batches(rt, jobs)
    many = [g for g in groups if len(g) > 1]
    one = list(alone) + [g[0] for g in groups if len(g) == 1]
    parallel = max(1, int(rt.acfg.get("parallel_llm", 3)))
    with cf.ThreadPoolExecutor(parallel) as pool:
        futures = [pool.submit(single, rt, item, n) for n, item in one]
        for verdicts, rest in pool.map(lambda group: _safe_batch(rt, group), many):
            _record(rt, verdicts)
            futures += [pool.submit(single, rt, item, n) for n, item in rest]
        _record(rt, {f.result()["item_id"]: f.result() for f in futures})


def _record(rt, verdicts: dict[str, dict]) -> None:
    for iid, verdict in verdicts.items():
        rt.verdicts[iid] = verdict
        if verdict.get("stop") == "final" and verdict["decision"] in REUSABLE:
            rt.pattern_verdicts.setdefault(reuse_key(rt, rt.items[iid]), verdict)


def _reuse(rt, item: CleanupItem) -> bool:
    """Give the item the cautious verdict of an earlier candidate with an identical pattern."""
    source = rt.pattern_verdicts.get(reuse_key(rt, item))
    if source is None:
        return False
    unit = rt.items[source["item_id"]].unit.key
    framework = _framework(rt, item)
    lessons = rt.lessons.matching(item, framework) if rt.ablation != "no_lessons" else []
    rt.verdicts[item.item_id] = {
        "item_id": item.item_id,
        "decision": source["decision"],
        "reason": f"Same pattern as {unit}: {source['reason']}",
        "evidence": [
            {"result": source["item_id"], "tool": "reuse", "says": f"the verdict on {unit}"}
        ],
        "lessons_cited": [les["lesson_id"] for les in lessons],
        "confidence": source.get("confidence"),
        "stop": "reused",
        "reused_from": source["item_id"],
        "agent": NAME,
    }
    text = f"{item.unit.key} has the same pattern as {unit}: {source['decision']} reused"
    rt.log.emit(
        "decision",
        agent=NAME,
        payload={"rule": "reuse", "item_id": item.item_id, "from": source["item_id"], "text": text},
    )
    return True


def _safe_batch(rt, jobs) -> tuple[dict[str, dict], list]:
    """One batch; if it fails, every candidate in it goes to the single investigation."""
    try:
        return investigate_batch(rt, jobs)
    except Exception as exc:
        rt.log.emit(
            "log",
            agent=f"{NAME}#{jobs[0][0]}",
            payload={"level": "ERROR", "message": f"batch: {type(exc).__name__}: {exc}"},
        )
        return {}, list(jobs)


def investigate_batch(rt, jobs: list[tuple[int, CleanupItem]]) -> tuple[dict[str, dict], list]:
    """One Investigator request for a few candidates with the same pattern: (verdicts by item,
    the jobs whose verdict was missing or broke a rule)."""
    agent = f"{NAME}#{jobs[0][0]}"
    budget = rt.budget(NAME)
    ids = [item.item_id for _, item in jobs]
    pattern = ", ".join(filter(None, pattern_key(rt, jobs[0][1])))
    rt.log.emit(
        "decision",
        agent=agent,
        payload={
            "rule": "batch",
            "items": ids,
            "pattern": pattern,
            "text": f"{len(jobs)} candidates with the same pattern ({pattern}) in one request",
        },
    )
    steps, own, lessons, sections = [], {}, {}, []
    for _, item in jobs:
        framework = _framework(rt, item)
        found = rt.lessons.matching(item, framework) if rt.ablation != "no_lessons" else []
        lessons[item.item_id] = found
        first = first_checks(rt, item, agent, start=len(steps))
        own[item.item_id] = {s["result_id"] for s in first}
        steps += first
        sections.append(
            task_text(rt, item, found)
            + "\nResults of the first checks (cite them):\n"
            + "\n".join(f"{s['result_id']} {s['tool']}: {s['result']}" for s in first)
        )
    task = f"{len(jobs)} candidates with the same pattern; give one verdict for each.\n\n"
    result = react(
        agent,
        rt.llm,
        load_prompt(f"{NAME}_batch"),
        task + "\n\n".join(sections),
        rt.tools,
        BATCH_SCHEMA,
        budget,
        rt.log,
        steps=steps,
    )
    rt.record_usage(agent, budget)
    if result.final is None:
        return {}, list(jobs)
    answers: dict[str, dict] = {}
    for verdict in result.final["verdicts"]:
        if isinstance(verdict.get("item_id"), str):
            answers.setdefault(verdict["item_id"], verdict)
    later = {s["result_id"] for s in result.steps} - {s["result_id"] for s in steps}
    tools = {s["result_id"]: s["tool"] for s in result.steps}
    verdicts, fallback = {}, []
    for n, item in jobs:
        answer = answers.get(item.item_id)
        problem = _problem(answer, result.steps, own[item.item_id] | later, lessons[item.item_id])
        if problem:
            rt.log.emit(
                "log",
                agent=agent,
                payload={"level": "WARNING", "message": f"{item.item_id}: {problem}; asked alone"},
            )
            fallback.append((n, item))
            continue
        verdicts[item.item_id] = {
            "item_id": item.item_id,
            "decision": answer["decision"],
            "reason": answer["reason"],
            "evidence": [{**e, "tool": tools.get(e.get("result"))} for e in answer["evidence"]],
            "lessons_cited": answer.get("lessons_cited", []),
            "confidence": answer.get("confidence"),
            "stop": "final",
            "agent": agent,
            "batch": ids,
        }
    return verdicts, fallback


def _problem(answer, steps: list[dict], own: set[str], lessons: list[dict]) -> str | None:
    """Why one candidate's verdict in a batch can't be used, or None: the single investigation's
    rules, and a safe verdict must cite a result about this candidate."""
    if answer is None:
        return "no verdict for it"
    try:
        jsonschema.validate(answer, FINAL_SCHEMA)
    except jsonschema.ValidationError as exc:
        return f"invalid verdict ({exc.message[:120]})"
    if problem := _checker(lessons)(answer, steps):
        return problem
    cited = {e.get("result") for e in answer["evidence"]}
    if answer["decision"] == "safe" and not cited & own:
        return "a safe verdict cites no result about this candidate"
    return None
