"""The JSON ReAct protocol every agent step uses.

A reply is {"thought": "<one line>", "tool": name, "args": {...}} or {"final": {...}}. It is
checked against a JSON schema; an invalid reply gets one repair turn that quotes the problem.
Chosen in Phase 0 (docs/agentic_design.md, section 2)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

from cleansweep.llm import LLMError
from cleansweep.llm.client import parse_json_text

from .budgets import Budget, BudgetExhausted
from .llm import acting

PROMPTS = Path(__file__).parent / "prompts"
REASONING_OFF = {"chat_template_kwargs": {"enable_thinking": False}}
RESULT_CHARS = 2000
FORMAT = (
    "Reply with ONE JSON object and nothing else, either\n"
    '{"thought": "<one line>", "tool": "<tool name>", "args": {...}}\n'
    "to use a tool, or, when you are done,\n"
    '{"final": <your answer as described above>}'
)


def load_prompt(agent: str) -> str:
    """An agent's system prompt, from prompts/<agent>.txt."""
    return (PROMPTS / f"{agent}.txt").read_text(encoding="utf-8").strip()


@dataclass
class ReactResult:
    final: dict | None
    stop: str  # "final", "budget", "invalid", "llm_error"
    steps: list[dict] = field(default_factory=list)  # {"result_id", "tool", "args", "result"}
    detail: str = ""


def parse_reply(
    text: str, tool_schemas: dict[str, dict], final_schema: dict
) -> tuple[str, dict, str | None]:
    """("tool"|"final", payload, problem). payload is {"tool","args","thought"} or the final."""
    try:
        obj = parse_json_text(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return "invalid", {}, f"not JSON ({str(exc)[:80]})"
    if not isinstance(obj, dict):
        return "invalid", {}, "the reply is not a JSON object"
    if "final" in obj:
        try:
            jsonschema.validate(obj["final"], final_schema)
        except jsonschema.ValidationError as exc:
            return "invalid", obj, f"final answer: {exc.message[:160]}"
        return "final", obj["final"], None
    name, args = obj.get("tool"), obj.get("args", {})
    if name not in tool_schemas:
        return "invalid", obj, f"unknown tool {name!r}; tools: {', '.join(sorted(tool_schemas))}"
    if not isinstance(args, dict):
        return "invalid", obj, "args must be a JSON object"
    try:
        jsonschema.validate(args, tool_schemas[name])
    except jsonschema.ValidationError as exc:
        return "invalid", obj, f"args for {name}: {exc.message[:160]}"
    return "tool", {"tool": name, "args": args, "thought": str(obj.get("thought", ""))[:300]}, None


def react(
    agent: str,
    llm,
    system: str,
    task: str,
    tools,
    final_schema: dict,
    budget: Budget,
    log=None,
    check_final: Callable[[dict, list[dict]], str | None] | None = None,
    extra_body: dict | None = None,
) -> ReactResult:
    """Run one agent's ReAct loop until it gives a valid final answer or a budget ends.

    tools is a ToolSet (name -> schema, call). check_final(final, steps) can reject a final
    answer that is valid JSON but breaks a rule (e.g. cites no tool result); the agent gets one
    repair turn for it, as for any invalid reply."""
    messages = [
        {"role": "system", "content": f"{system}\n\nTools:\n{tools.describe()}\n\n{FORMAT}"},
        {"role": "user", "content": task},
    ]
    steps: list[dict] = []
    repaired = False
    with acting(agent, budget):
        while True:
            try:
                budget.charge_step()
                text = llm.chat(messages, extra_body=extra_body or REASONING_OFF)
            except BudgetExhausted as exc:
                _budget_event(log, agent, str(exc))
                return ReactResult(None, "budget", steps, str(exc))
            except LLMError as exc:
                return ReactResult(None, "llm_error", steps, str(exc))
            kind, payload, problem = parse_reply(text, tools.schemas(), final_schema)
            if kind == "final" and check_final is not None:
                problem = check_final(payload, steps)
                kind = "invalid" if problem else kind
            if kind == "invalid":
                if repaired:
                    return ReactResult(None, "invalid", steps, problem or "")
                repaired = True
                messages += [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": f"That reply was not valid: {problem}. {FORMAT}"},
                ]
                continue
            repaired = False
            if kind == "final":
                return ReactResult(payload, "final", steps)
            result_id = f"R{len(steps) + 1}"
            if log is not None and payload["thought"]:
                log.emit("thought", agent=agent, payload={"text": payload["thought"]})
            call = (
                log.emit(
                    "tool_call",
                    agent=agent,
                    payload={"tool": payload["tool"], "args": payload["args"]},
                )
                if log
                else None
            )
            result = tools.call(payload["tool"], payload["args"])
            result = (
                result
                if len(result) <= RESULT_CHARS
                else result[: RESULT_CHARS - 20] + "\n...(truncated)"
            )
            if log is not None:
                log.emit(
                    "tool_result",
                    agent=agent,
                    parent=call["id"] if call else None,
                    payload={"result_id": result_id, "tool": payload["tool"], "result": result},
                )
            steps.append(
                {
                    "result_id": result_id,
                    "tool": payload["tool"],
                    "args": payload["args"],
                    "result": result,
                }
            )
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"Observation {result_id}: {result}"},
            ]


def _budget_event(log, agent: str, why: str) -> None:
    if log is not None:
        log.emit("budget", agent=agent, payload={"exhausted": why})
