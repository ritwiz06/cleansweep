from .client import LLMClient
from .fake import FakeLLM


def get_client(cfg: dict | None = None) -> FakeLLM:
    return FakeLLM()


__all__ = ["FakeLLM", "LLMClient", "get_client"]
