# Cleanup report: toy_repo

**Result: everything runs.** 7 cleanup edits applied in 7 work packages; 44 lines and 3 files removed.

A Python project with 17 Python files.

## Tests

- Environment: installed into .cs_venv (next to the workspace)
- Baseline (3 runs): 15 passing in every run, 0 already failing, 0 flaky.
- After the cleanup: 15 passing; new failures: none.

## Work packages

| Package | Goal | Outcome | Commit |
|---|---|---|---|
| P1 | Remove 1 unused import in shopcart/cart.py | kept | cd48189220 |
| P2 | Remove 1 unused import in shopcart/commands.py | kept | f4550ca939 |
| P3 | Remove 1 leftover file in debug_cart.py | kept | a9f9f9bffa |
| P4 | Remove 1 leftover file in reproduce_bug.py | kept | 297e4b2ac4 |
| P5 | Remove 1 unused dependency in requirements.txt | kept | aec853132f |
| P6 | Remove 1 leftover file in shopcart/pricing_old.py | kept | 93fa739cc6 |
| P7 | Remove 1 one-use wrapper in shopcart/cart.py | rolled back |  |
| P8 | Remove 1 duplicate in shopcart/discounts.py | rolled back |  |
| P9 | Remove 1 duplicate in shopcart/storage.py | rolled back |  |
| P10 | Remove 1 unused function or class in shopcart/utils.py | kept | ff736853fc |

## Rolled back

- `shopcart/cart.py::compute_total`: unverified failed: the probes ran no cases, so these rewrites are not verified: ['shopcart/cart.py::compute_total']
- `shopcart/discounts.py::_round_price`: unverified failed: the probes ran no cases, so these rewrites are not verified: ['shopcart/discounts.py::_round_price']
- `shopcart/storage.py::_safe_round`: unverified failed: the probes ran no cases, so these rewrites are not verified: ['shopcart/storage.py::_safe_round']

## Suggestions (not applied)

- `shopcart/pricing.py` (format): The project doesn't enforce a formatter (no ruff format or black in its CI config or .pre-commit-config.yaml), so reformatting is only suggested.
- `shopcart/commands.py::cmd_add` (dead_code): Investigator (suggest): It may be used in ways the code graph can't see (dynamic use or a framework callback).
- `shopcart/commands.py::cmd_export` (dead_code): Investigator (suggest): It may be used in ways the code graph can't see (dynamic use or a framework callback).
- `shopcart/commands.py::cmd_load` (dead_code): Investigator (suggest): It may be used in ways the code graph can't see (dynamic use or a framework callback).
- `shopcart/commands.py::cmd_total` (dead_code): Investigator (suggest): It may be used in ways the code graph can't see (dynamic use or a framework callback).
- `shopcart/storage.py::load_legacy` (security): Possible security problem: Use of possibly insecure function - consider using safer ast.literal_eval.
- `reproduce_bug.py::L6-6` (debug_leftover): A print in library code; it may be leftover debugging or intended output.

## Lessons learned

- L1: unverified failed after replace_with of shopcart/cart.py::compute_total: the probes ran no cases, so these rewrites are not verified: ['shopcart/cart.py::compute_total']
- L2: unverified failed after replace_with of shopcart/discounts.py::_round_price: the probes ran no cases, so these rewrites are not verified: ['shopcart/discounts.py::_round_price']
- L3: unverified failed after replace_with of shopcart/storage.py::_safe_round: the probes ran no cases, so these rewrites are not verified: ['shopcart/storage.py::_safe_round']

## How the run went

- Phases: ONBOARD → BASELINE → AUDIT → INVESTIGATE → PLAN → EXECUTE → FINAL_VERIFY → REPORT
- Test runs: 14; LLM requests: 0; tokens: 0 prompt + 0 completion.
- Secret scan: 0 secret files withheld, 0 secret-looking strings redacted before any LLM request.

| Agent | Turns | Instances | Tool steps | LLM requests | Seconds |
|---|---|---|---|---|---|
| auditor | 1 | 1 | 2 | 0 | 0.5 |
| engineer | 17 | 1 | 10 | 0 | 1.5 |
| explorer | 1 | 1 | 0 | 0 | 0.0 |
| fixer | 3 | 1 | 0 | 0 | 0.1 |
| investigator | 1 | 14 | 22 | 0 | 0.1 |
| planner | 1 | 1 | 0 | 0 | 0.0 |
| tester | 12 | 1 | 4 | 0 | 10.9 |
| validator | 10 | 1 | 0 | 0 | 1.8 |

## Delivery

- Branch `cleansweep/cleanup-20261101-163332` in `/private/tmp/cs-studio-rec/20261101_toy_clean_offline/workspace`: 7 commits, one per work package.
- Patches: `/private/tmp/cs-studio-rec/20261101_toy_clean_offline/patches`
- Nothing was applied to the original folder.
