from cleansweep.agents.budgets import Budget
from cleansweep.agents.protocol import parse_reply, react
from cleansweep.agents.scripted import ScriptedLLM, final, tool
from cleansweep.agents.tools import Tool, ToolSet

FINAL = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
TOOLS = ToolSet(
    [
        Tool(
            "echo",
            "Echo text.",
            {"text": {"type": "string"}},
            ["text"],
            lambda text: f"echo: {text}",
        )
    ]
)


def test_parse_reply_kinds():
    schemas = TOOLS.schemas()
    assert parse_reply(tool("echo", {"text": "hi"}), schemas, FINAL)[0] == "tool"
    assert parse_reply("```json\n" + final({"answer": "x"}) + "\n```", schemas, FINAL) == (
        "final",
        {"answer": "x"},
        None,
    )
    assert "unknown tool" in parse_reply(tool("rm", {}), schemas, FINAL)[2]
    assert "args for echo" in parse_reply(tool("echo", {"text": 3}), schemas, FINAL)[2]
    assert "final answer" in parse_reply(final({"wrong": 1}), schemas, FINAL)[2]
    assert parse_reply("I think so.", schemas, FINAL)[0] == "invalid"


def test_react_uses_tools_then_finishes():
    llm = ScriptedLLM([("task", [tool("echo", {"text": "hi"}), final({"answer": "done"})])])
    result = react("agent", llm, "system", "the task", TOOLS, FINAL, Budget(steps=5))
    assert result.stop == "final" and result.final == {"answer": "done"}
    assert result.steps[0]["result"] == "echo: hi"
    assert "Observation R1: echo: hi" in llm.calls[-1][-1]["content"]


def test_one_repair_turn_then_give_up():
    llm = ScriptedLLM([("task", ["not json", final({"answer": "fixed"})])])
    assert react("a", llm, "s", "the task", TOOLS, FINAL, Budget(steps=5)).final == {
        "answer": "fixed"
    }
    llm = ScriptedLLM([("task", ["not json", "still not json"])])
    result = react("a", llm, "s", "the task", TOOLS, FINAL, Budget(steps=5))
    assert result.stop == "invalid" and result.final is None


def test_a_rule_check_on_the_final_answer_gets_one_repair():
    llm = ScriptedLLM([("task", [final({"answer": "x"}), final({"answer": "y"})])])
    result = react(
        "a",
        llm,
        "s",
        "the task",
        TOOLS,
        FINAL,
        Budget(steps=5),
        check_final=lambda f, steps: None if f["answer"] == "y" else "answer y",
    )
    assert result.final == {"answer": "y"}


def test_a_step_budget_ends_the_loop():
    llm = ScriptedLLM([("task", [tool("echo", {"text": "again"})])])
    result = react("a", llm, "s", "the task", TOOLS, FINAL, Budget(steps=3))
    assert result.stop == "budget" and len(result.steps) == 3
