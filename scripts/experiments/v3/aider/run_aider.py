"""Aider's own command line, with each test run and each shell command Aider proposes logged as
one JSON line in the file CS_AIDER_LOG names. Runs inside the cs-aider image
(/opt/aider/bin/python); Aider's code is not changed, only Commands.cmd_test and
Coder.handle_shell_commands are wrapped to observe them (auto-yes still declines the commands).
LLM requests are counted by the runner's relay on the host."""

import json
import os
import sys
import time

from aider.coders.base_coder import Coder
from aider.commands import Commands
from aider.main import main

LOG = os.environ["CS_AIDER_LOG"]
cmd_test = Commands.cmd_test
handle_shell_commands = Coder.handle_shell_commands


def _log(record: dict) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


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


def logged_shell(self, commands_str, group):
    _log({"kind": "shell", "t": round(time.time(), 2), "commands": commands_str})
    return handle_shell_commands(self, commands_str, group)


Commands.cmd_test = logged_test
Coder.handle_shell_commands = logged_shell
sys.exit(main())
