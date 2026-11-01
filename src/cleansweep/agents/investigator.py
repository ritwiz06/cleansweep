"""Investigator: a ReAct loop per candidate that ends in safe / suggest / drop, with an evidence
chain in which every step cites a tool result, and the lessons it used.

The Investigator can only make a candidate more cautious than its detector lane: an item is
applied only if the detector put it in the safe lane and the Investigator says "safe"."""

from __future__ import annotations

import concurrent.futures as cf
from pathlib import Path

from cleansweep.core.models import CleanupItem

from .protocol import load_prompt, react

NAME = "investigator"
FINAL_SCHEMA = {
    "type": "object",
    "required": ["decision", "reason", "evidence"],
    "properties": {
        "decision": {"enum": ["safe", "suggest", "drop"]},
        "reason": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["result"],
                "properties": {"result": {"type": "string"}, "says": {"type": "string"}},
            },
        },
        "lessons_cited": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
}
FORMAT_REASON = "Formatting only; the Validator checks that the code structure is unchanged."
OUT_OF_SCOPE = (
    "The project's formatter check runs only on {scope}, not on {path}, so reformatting it is "
    "only suggested."
)
NO_FORMATTER = (
    "The project doesn't enforce a formatter (no ruff format or black in its CI config or "
    ".pre-commit-config.yaml), so reformatting is only suggested."
)


def _short(item: CleanupItem) -> str:
    return (item.unit.name or "").split(".")[-1] or Path(item.unit.path).stem


def _framework(rt, item: CleanupItem) -> str | None:
    return rt.graph.framework_callback(item.unit.key) if item.unit.name else None


def task_text(rt, item: CleanupItem, lessons: list[dict]) -> str:
    """What the Investigator is told about one candidate."""
    unit = item.unit
    where = f"{unit.path} lines {unit.start_line}-{unit.end_line}" if unit.start_line else unit.path
    lines = [
        f"Candidate {item.item_id}",
        f"unit: {unit.key} ({unit.kind}) at {where}",
        f"category: {item.category}; proposed edit: {item.action}; detector lane: {item.lane}",
        f"detector reason: {item.reason}",
        "detector evidence: " + "; ".join(item.evidence[:6]),
    ]
    if item.keep_target:
        lines.append(f"the copy that would be kept: {item.keep_target}")
    if lessons:
        lines.append("Lessons that fit this candidate (cite them):")
        lines += [f"- {les['lesson_id']}: {les['reason']}" for les in lessons]
    else:
        lines.append("No lesson fits this candidate so far.")
    return "\n".join(lines)


def _checker(lessons: list[dict]):
    wanted = {les["lesson_id"] for les in lessons}

    def check(final: dict, steps: list[dict]) -> str | None:
        ids = {s["result_id"] for s in steps}
        cited = {e.get("result") for e in final.get("evidence", [])}
        if final["decision"] == "safe" and not cited & ids:
            return "a safe decision needs evidence that cites a tool result (R1, R2, ...)"
        if cited - ids:
            have = sorted(ids) or "no results"
            return f"evidence cites {sorted(cited - ids)}, but this investigation has only {have}"
        missing = wanted - set(final.get("lessons_cited", []))
        if missing:
            return f"cite the lessons that fit this candidate: {sorted(missing)}"
        return None

    return check


def first_checks(rt, item: CleanupItem, agent: str) -> list[dict]:
    """The checks every investigation starts with, run before the LLM is asked: references,
    dynamic use and lessons. Their results are R1, R2, ... in the task."""
    name = _short(item)
    calls = [("find_references", {"name": name})]
    if item.unit.name:
        calls.append(("check_dynamic_use", {"name": name}))
    if rt.ablation != "no_lessons":
        calls.append(("query_lessons", {"pattern": name}))
    steps = []
    for tool_name, args in calls:
        call = rt.log.emit("tool_call", agent=agent, payload={"tool": tool_name, "args": args})
        result = rt.tools.call(tool_name, args)[:1500]
        rid = f"R{len(steps) + 1}"
        rt.log.emit(
            "tool_result",
            agent=agent,
            parent=call["id"],
            payload={"result_id": rid, "tool": tool_name, "result": result},
        )
        steps.append({"result_id": rid, "tool": tool_name, "args": args, "result": result})
    return steps


def investigate_llm(rt, item: CleanupItem, n: int) -> dict:
    agent = f"{NAME}#{n}"
    budget = rt.budget(NAME)
    if item.item_id in rt.retry:  # sent back by the Manager: twice the steps and LLM calls
        budget.steps, budget.llm_calls = budget.steps * 2, budget.llm_calls * 2
    lessons = rt.lessons.matching(item, _framework(rt, item)) if rt.ablation != "no_lessons" else []
    first = first_checks(rt, item, agent)
    task = (
        task_text(rt, item, lessons)
        + "\n\nResults of the first checks (cite them):\n"
        + "\n".join(f"{s['result_id']} {s['tool']}: {s['result']}" for s in first)
    )
    result = react(
        agent,
        rt.llm,
        load_prompt(NAME),
        task,
        rt.tools,
        FINAL_SCHEMA,
        budget,
        rt.log,
        check_final=_checker(lessons),
        steps=first,
    )
    rt.record_usage(agent, budget)
    if result.final is None:
        why = {
            "budget": "its budget ran out",
            "invalid": "its answer stayed invalid",
            "llm_error": "the LLM request failed",
        }
        return {
            "item_id": item.item_id,
            "decision": "suggest",
            "reason": "The Investigator could not decide: "
            f"{why.get(result.stop, result.stop)} ({result.detail[:120]}).",
            "evidence": _chain(result.steps),
            "lessons_cited": [les["lesson_id"] for les in lessons],
            "stop": result.stop,
            "agent": agent,
        }
    final = result.final
    return {
        "item_id": item.item_id,
        "decision": final["decision"],
        "reason": final["reason"],
        "evidence": [
            {
                **e,
                "tool": next(
                    (s["tool"] for s in result.steps if s["result_id"] == e.get("result")), None
                ),
            }
            for e in final["evidence"]
        ],
        "lessons_cited": final.get("lessons_cited", []),
        "confidence": final.get("confidence"),
        "stop": "final",
        "agent": agent,
    }


def _chain(steps: list[dict]) -> list[dict]:
    return [{"result": s["result_id"], "tool": s["tool"], "says": s["result"][:200]} for s in steps]


def investigate_rules(rt, item: CleanupItem, n: int) -> dict:
    """The offline investigation: the same evidence tools, decided by rules."""
    agent = f"{NAME}#{n}"
    steps: list[dict] = []

    def use(tool: str, args: dict) -> str:
        call = rt.log.emit("tool_call", agent=agent, payload={"tool": tool, "args": args})
        result = rt.tools.call(tool, args)
        rid = f"R{len(steps) + 1}"
        rt.log.emit(
            "tool_result",
            agent=agent,
            parent=call["id"],
            payload={"result_id": rid, "tool": tool, "result": result},
        )
        steps.append({"result_id": rid, "tool": tool, "args": args, "result": result})
        return result

    framework = _framework(rt, item)
    lessons = rt.lessons.matching(item, framework) if rt.ablation != "no_lessons" else []
    if item.category in ("dead_code", "duplicate", "wrapper") and item.unit.name:
        use("check_dynamic_use", {"name": _short(item)})
    if rt.ablation != "no_lessons":
        use("query_lessons", {"pattern": _short(item)})
    if lessons:
        decision = "suggest"
        reason = f"A lesson from an earlier rollback fits: {lessons[0]['reason']}"
    elif framework or rt.graph.dynamic_risk(item.unit.key):
        decision = "suggest"
        reason = (
            "It may be used in ways the code graph can't see (dynamic use or a framework callback)."
        )
    elif item.lane == "safe":
        decision, reason = (
            "safe",
            "No evidence that it is still used; the checks after the edit will confirm.",
        )
    else:
        decision, reason = "suggest", item.reason
    return {
        "item_id": item.item_id,
        "decision": decision,
        "reason": reason,
        "evidence": _chain(steps),
        "lessons_cited": [les["lesson_id"] for les in lessons],
        "stop": "rules",
        "agent": agent,
    }


THOROUGH = {"duplicate", "wrapper"}  # rewrites thorough mode applies when the probes verify them
THOROUGH_NOTE = "thorough mode: applied as a rewrite only if the probes run cases on it"


def apply_verdict(item: CleanupItem, verdict: dict, mode: str = "safe") -> None:
    """Update the item's lane: never riskier than the detector's lane, except that thorough mode
    takes the Investigator's word on duplicates and wrappers (the probes then have to verify
    the rewrite on its own cases, or it is rolled back)."""
    promote = (
        mode == "thorough"
        and verdict["decision"] == "safe"
        and item.lane == "suggest"
        and item.category in THOROUGH
        and bool(item.keep_target or item.patch)
    )
    if verdict["decision"] == "safe" and item.lane == "safe" and item.action != "report_only":
        lane = "safe"
    elif promote:
        lane, item.action = "safe", "replace_with"
        item.sources.append("thorough")
    else:
        lane = "suggest"
    if verdict["decision"] == "drop":
        item.action = "report_only"
    item.lane = lane
    if item.category == "format" and lane == "suggest":
        item.reason = verdict["reason"]
    elif item.category != "format" and verdict.get("stop") != "rule":
        if promote:
            item.reason = f"Investigator (safe): {verdict['reason']} ({THOROUGH_NOTE})"
        elif verdict["decision"] == "safe" and lane == "suggest":
            # the detector or a policy (public API, framework callback) keeps it a suggestion
            item.reason = f"{item.reason} The Investigator found no use either: {verdict['reason']}"
        else:
            item.reason = f"Investigator ({verdict['decision']}): {verdict['reason']}"
    item.evidence += [
        f"{e.get('result')}: {e.get('says', '')}"[:200] for e in verdict.get("evidence", [])
    ]
    item.evidence += [f"lesson {les}" for les in verdict.get("lessons_cited", [])]
    if "investigator" not in item.sources:
        item.sources.append("investigator")
    if verdict.get("confidence") is not None:
        item.llm_confidence = float(verdict["confidence"])


LINE_LEVEL = {"unused_variable", "debug_leftover", "commented_code", "todo_note", "redundant_check"}
LINE_REASON = "A line-level edit: the detector's lane stands, and the checks after the edit decide."


def _covered(path: str, scope: list[str] | None) -> bool:
    return scope is None or any(path == s or path.startswith(s.rstrip("/") + "/") for s in scope)


def package_data(repo_dir: str, path: str) -> str | None:
    """Why a non-Python file is package data, or None: it sits in a folder of an importable
    package with other files of its type, which code usually loads by name or by listing the
    folder, so "nothing imports it" says nothing."""
    file = Path(repo_dir) / path
    if file.suffix == ".py" or not file.suffix:
        return None
    folder = file.parent
    package = next((p for p in [folder, *folder.parents] if (p / "__init__.py").exists()), None)
    if package is None or Path(repo_dir).resolve() not in package.resolve().parents:
        return None
    siblings = [f for f in folder.glob(f"*{file.suffix}") if f.name != file.name]
    if len(siblings) < 2:
        return None
    where = folder.relative_to(repo_dir).as_posix()
    return (
        f"{path} is one of {len(siblings) + 1} {file.suffix} files in {where}, inside the "
        f"{package.name} package: package data like this is usually loaded by name or by "
        "listing the folder, so no import refers to it. A person should decide."
    )


def _fixed(
    item: CleanupItem,
    brief: dict | None = None,
    policy: str = "enforced",
    repo_dir: str | None = None,
) -> dict | None:
    if item.category in LINE_LEVEL:
        decision = "safe" if item.lane == "safe" else "suggest"
        reason = LINE_REASON if decision == "safe" else item.reason
        return {
            "item_id": item.item_id,
            "decision": decision,
            "reason": reason,
            "evidence": [],
            "stop": "rule",
        }
    if item.category == "format":
        # safe only where the project enforces a formatter on this file, unless the policy
        # is "always"
        brief = brief or {}
        scope = brief.get("formatter_paths")
        enforced = policy == "always" or brief.get("formatter")
        covered = policy == "always" or _covered(item.unit.path, scope)
        reason = FORMAT_REASON
        if not enforced:
            reason = NO_FORMATTER
        elif not covered:
            reason = OUT_OF_SCOPE.format(path=item.unit.path, scope=", ".join(scope or []))
        return {
            "item_id": item.item_id,
            "decision": "safe" if enforced and covered else "suggest",
            "reason": reason,
            "evidence": [],
            "stop": "rule",
        }
    data = package_data(repo_dir, item.unit.path) if repo_dir else None
    if item.category == "leftover_file" and data:
        return {
            "item_id": item.item_id,
            "decision": "suggest",
            "reason": data,
            "evidence": [],
            "stop": "rule",
        }
    if item.category == "security":
        return {
            "item_id": item.item_id,
            "decision": "suggest",
            "reason": "Security findings are reported for a person; "
            "they are never edited automatically.",
            "evidence": [],
            "stop": "rule",
        }
    return None


def _isolated(fn):
    """One candidate's failure is that candidate's "suggest", not the end of the phase."""

    def run_one(rt, item: CleanupItem, n: int) -> dict:
        try:
            return fn(rt, item, n)
        except Exception as exc:
            rt.log.emit(
                "log",
                agent=f"{NAME}#{n}",
                payload={"level": "ERROR", "message": f"{type(exc).__name__}: {exc}"},
            )
            return {
                "item_id": item.item_id,
                "decision": "suggest",
                "reason": f"The investigation failed ({type(exc).__name__}); a person should look.",
                "evidence": [],
                "stop": "error",
                "agent": f"{NAME}#{n}",
            }

    return run_one


def run(rt) -> None:
    """INVESTIGATE: a verdict for every candidate, up to `parallel_llm` at once."""
    pending = [i for i in rt.items.values() if i.item_id not in rt.verdicts]
    use_llm = rt.llm is not None and rt.ablation != "no_research"
    work = []
    for n, item in enumerate(pending, 1):
        fixed = _fixed(item, rt.brief, rt.acfg.get("format_policy", "enforced"), rt.ws.path)
        if fixed is not None:
            rt.verdicts[item.item_id] = fixed
        else:
            work.append((n, item))
    fn = _isolated(investigate_llm if use_llm else investigate_rules)
    workers = int(rt.acfg.get("parallel_llm", 3)) if use_llm else 1
    with cf.ThreadPoolExecutor(max(1, workers)) as pool:
        for verdict in pool.map(lambda job: fn(rt, job[1], job[0]), work):
            rt.verdicts[verdict["item_id"]] = verdict
    for item in pending:
        verdict = rt.verdicts[item.item_id]
        rt.before_verdict[item.item_id] = (
            item.lane,
            item.action,
            item.reason,
            list(item.evidence),
            list(item.sources),
        )
        apply_verdict(item, verdict, rt.mode)
        rt.log.emit(
            "decision",
            agent=verdict.get("agent", NAME),
            payload={
                "item_id": item.item_id,
                "unit": item.unit.key,
                "decision": verdict["decision"],
                "lane": item.lane,
                "reason": verdict["reason"],
                "lessons_cited": verdict.get("lessons_cited", []),
                "stop": verdict.get("stop"),
            },
        )
        rt.board.post(
            "verdict",
            verdict.get("agent", NAME),
            {
                "item_id": item.item_id,
                "decision": verdict["decision"],
                "reason": verdict["reason"],
                "evidence": verdict.get("evidence", []),
                "lessons_cited": verdict.get("lessons_cited", []),
                "confidence": verdict.get("confidence") or 0.0,
            },
        )
    rt.investigated = True
