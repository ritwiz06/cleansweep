# Cleanup report: shop_app

**Result: everything runs.** 5 cleanup edits applied in 5 work packages; 47 lines and 2 files removed.

A Python project with 16 Python files.

## Tests

- Environment: not needed
- Baseline (3 runs): 12 passing in every run, 0 already failing, 0 flaky.
- After the cleanup: 12 passing; new failures: none.

## Work packages

| Package | Goal | Outcome | Commit |
|---|---|---|---|
| P1 | Remove 1 leftover file in bookshelf/inventory_old.py | kept | a3fb639012 |
| P2 | Remove 1 leftover file in scratch_restock.py | kept | 3674487b3f |
| P3 | Remove 1 unused function or class in bookshelf/inventory.py | kept | 6aa0c43107 |
| P4 | Remove 1 duplicate in bookshelf/orders.py | rolled back |  |
| P5 | Remove 1 duplicate in bookshelf/reports.py | kept | e81ca1d56f |
| P6 | Remove 1 unused function or class in bookshelf/utils.py | kept | 5435772ae8 |

## Rolled back

- `bookshelf/orders.py::_round_money`: probes failed: probes found a behavior change:

## Suggestions (not applied)

- `bookshelf/commands.py::cmd_add` (dead_code): cmd_add is never called anywhere in the project. The Investigator found no use either: No static or dynamic references found; the function is unused dead code.
- `bookshelf/commands.py::cmd_load` (dead_code): cmd_load is never called anywhere in the project. The Investigator found no use either: No static or dynamic references found; the function is unused dead code.
- `bookshelf/commands.py::cmd_lowstock` (dead_code): cmd_lowstock is never called anywhere in the project. The Investigator found no use either: No static or dynamic references found in code, tests, or configs. The function is unused dead code.
- `bookshelf/commands.py::cmd_order` (dead_code): cmd_order is never called anywhere in the project. The Investigator found no use either: No static or dynamic references found; the function is unused dead code.
- `bookshelf/commands.py::cmd_report` (dead_code): cmd_report is never called anywhere in the project. The Investigator found no use either: No references found in code, tests, or configs. No dynamic use or framework callbacks detected. The function is dead code.
- `bookshelf/commands.py::cmd_restock` (dead_code): cmd_restock is never called anywhere in the project. The Investigator found no use either: The function cmd_restock has no callers, no dynamic references, and is not part of any framework callback pattern. It is dead code.
- `bookshelf/commands.py::cmd_save` (dead_code): cmd_save is never called anywhere in the project. The Investigator found no use either: No static or dynamic references found; the function is unused dead code.
- `bookshelf/storage.py::load_legacy` (security): Possible security problem: Use of possibly insecure function - consider using safer ast.literal_eval.
- `bookshelf/inventory.py::L37-37` (debug_leftover): A print in library code; it may be leftover debugging or intended output.
- `scratch_restock.py::L8-8` (debug_leftover): A print in library code; it may be leftover debugging or intended output.

## Lessons learned

- L1: probes failed after replace_with of bookshelf/orders.py::_round_money: probes found a behavior change:

## How the run went

- Phases: ONBOARD → BASELINE → AUDIT → INVESTIGATE → PLAN → EXECUTE → FINAL_VERIFY → REPORT
- Test runs: 10; LLM requests: 38; tokens: 42064 prompt + 8363 completion.
- Secret scan: 0 secret files withheld, 0 secret-looking strings redacted before any LLM request.

| Agent | Turns | Instances | Tool steps | LLM requests | Seconds |
|---|---|---|---|---|---|
| auditor | 1 | 1 | 2 | 0 | 0.5 |
| engineer | 11 | 1 | 6 | 0 | 0.9 |
| explorer | 1 | 1 | 4 | 4 | 5.9 |
| fixer | 1 | 1 | 0 | 0 | 0.0 |
| investigator | 1 | 13 | 46 | 23 | 29.8 |
| manager | 0 | 1 | 0 | 6 | 0.0 |
| planner | 1 | 1 | 0 | 0 | 0.0 |
| tester | 8 | 1 | 3 | 0 | 4.7 |
| validator | 6 | 1 | 0 | 5 | 74.5 |

## Delivery

- An experiment run: the workspace is removed afterwards; the cleanup diff is `final.diff` (also `final_diff` in report.json).
- Nothing was applied to the original.
