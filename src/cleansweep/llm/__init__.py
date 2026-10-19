from cleansweep.core.registry import use_stub

from .client import LLMClient
from .fake import FakeLLM

if use_stub("llm"):
    from .stub import get_client
else:
    from .client import get_client

__all__ = ["FakeLLM", "LLMClient", "get_client"]
