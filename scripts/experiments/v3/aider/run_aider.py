"""Aider's own command line, with each LLM request and each test run logged as one JSON line in
the file CS_AIDER_LOG names. Runs inside the cs-aider image (/opt/aider/bin/python); Aider's code
is not changed, only Model.send_completion and Commands.cmd_test are wrapped to observe them.
Error messages are not logged (a provider error can quote a request): only their type."""

import json
import os
import sys
import time

from aider.commands import Commands
from aider.main import main
from aider.models import Model

LOG = os.environ["CS_AIDER_LOG"]
send_completion = Model.send_completion
cmd_test = Commands.cmd_test


def _log(record: dict) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def logged_send(self, messages, functions, stream, temperature=None):
    record = {"kind": "llm", "t": round(time.time(), 2), "model": self.name, "stream": stream}
    start = time.time()
    try:
        out = send_completion(self, messages, functions, stream, temperature)
        usage = getattr(out[1], "usage", None)
        record["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
        record["completion_tokens"] = getattr(usage, "completion_tokens", None)
        return out
    except BaseException as exc:
        record["error"] = type(exc).__name__
        raise
    finally:
        record["seconds"] = round(time.time() - start, 2)
        _log(record)


def logged_test(self, args):
    start = time.time()
    errors = cmd_test(self, args)
    _log(
        {
            "kind": "test",
            "t": round(start, 2),
            "seconds": round(time.time() - start, 2),
            "failed": bool(errors),
        }
    )
    return errors


Model.send_completion = logged_send
Commands.cmd_test = logged_test
sys.exit(main())
