from cleansweep.core.models import CleanupItem, CodeUnit
from cleansweep.llm import FakeLLM, LLMError
from cleansweep.reviewer import propose_fix

ITEM = CleanupItem(
    "a",
    CodeUnit("m.py", "function", "f"),
    "duplicate",
    "replace_with",
    "safe",
    "dup",
    patch="--- a/m.py\n+++ b/m.py\n",
)


def test_returns_diff_or_none():
    diff = "```diff\n--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-x\n+y\n```"
    assert propose_fix(ITEM, "boom", ".", FakeLLM({"failed": diff})).startswith("--- a/m.py")
    assert propose_fix(ITEM, "boom", ".", FakeLLM({"failed": "NO_FIX"})) is None
    assert propose_fix(ITEM, "boom", ".", None) is None


class TimesOut:
    def chat(self, messages, **kwargs):
        raise LLMError("APITimeoutError: Request timed out.")


def test_failed_request_is_no_fix():
    assert propose_fix(ITEM, "boom", ".", TimesOut()) is None
