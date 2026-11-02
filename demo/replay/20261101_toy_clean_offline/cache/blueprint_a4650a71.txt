# Cleanup blueprint: toy_repo

A Python project with 17 Python files.

Mode: safe. 10 work packages, applied one at a time; each is tested and checked, then kept as one commit, repaired, or rolled back.

## P1: Remove 1 unused import in shopcart/cart.py

- Risk tier: 0
- Files: shopcart/cart.py
- Edits:
  - remove_import `shopcart/cart.py::os` (unused_import): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes; related tests: tests/test_cart.py, tests/test_cli.py, tests/test_storage.py
- Rollback: reset the workspace to the checkpoint before P1; later packages are unaffected

## P2: Remove 1 unused import in shopcart/commands.py

- Risk tier: 0
- Files: shopcart/commands.py
- Edits:
  - remove_import `shopcart/commands.py::sys` (unused_import): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes; related tests: the full suite
- Rollback: reset the workspace to the checkpoint before P2; later packages are unaffected

## P3: Remove 1 leftover file in debug_cart.py

- Risk tier: 1
- Files: debug_cart.py
- Edits:
  - delete_file `debug_cart.py` (leftover_file): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes, public_api; related tests: the full suite
- Rollback: reset the workspace to the checkpoint before P3; later packages are unaffected

## P4: Remove 1 leftover file in reproduce_bug.py

- Risk tier: 1
- Files: reproduce_bug.py
- Edits:
  - delete_file `reproduce_bug.py` (leftover_file): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes, public_api; related tests: the full suite
- Rollback: reset the workspace to the checkpoint before P4; later packages are unaffected

## P5: Remove 1 unused dependency in requirements.txt

- Risk tier: 1
- Files: requirements.txt
- Edits:
  - remove_dependency `requirements.txt::requests` (unused_dependency): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes, dependency; related tests: the full suite
- Rollback: reset the workspace to the checkpoint before P5; later packages are unaffected

## P6: Remove 1 leftover file in shopcart/pricing_old.py

- Risk tier: 1
- Files: shopcart/pricing_old.py
- Edits:
  - delete_file `shopcart/pricing_old.py` (leftover_file): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes, public_api; related tests: the full suite
- Rollback: reset the workspace to the checkpoint before P6; later packages are unaffected

## P7: Remove 1 one-use wrapper in shopcart/cart.py

- Risk tier: 2
- Files: shopcart/cart.py
- Edits:
  - replace_with `shopcart/cart.py::compute_total` (wrapper): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes; related tests: tests/test_cart.py, tests/test_cli.py, tests/test_storage.py
- Rollback: reset the workspace to the checkpoint before P7; later packages are unaffected

## P8: Remove 1 duplicate in shopcart/discounts.py

- Risk tier: 2
- Files: shopcart/discounts.py
- Edits:
  - replace_with `shopcart/discounts.py::_round_price` (duplicate): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes; related tests: tests/test_discounts.py
- Rollback: reset the workspace to the checkpoint before P8; later packages are unaffected

## P9: Remove 1 duplicate in shopcart/storage.py

- Risk tier: 2
- Files: shopcart/storage.py
- Edits:
  - replace_with `shopcart/storage.py::_safe_round` (duplicate): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes; related tests: tests/test_storage.py
- Rollback: reset the workspace to the checkpoint before P9; later packages are unaffected

## P10: Remove 1 unused function or class in shopcart/utils.py

- Risk tier: 2
- Files: shopcart/utils.py
- Edits:
  - delete_unit `shopcart/utils.py::format_money_v2` (dead_code): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes, public_api; related tests: tests/test_pricing.py
- Rollback: reset the workspace to the checkpoint before P10; later packages are unaffected

## Suggestions (not applied)

- `shopcart/pricing.py` (format): The project doesn't enforce a formatter (no ruff format or black in its CI config or .pre-commit-config.yaml), so reformatting is only suggested.
- `shopcart/commands.py::cmd_add` (dead_code): Investigator (suggest): It may be used in ways the code graph can't see (dynamic use or a framework callback).
- `shopcart/commands.py::cmd_export` (dead_code): Investigator (suggest): It may be used in ways the code graph can't see (dynamic use or a framework callback).
- `shopcart/commands.py::cmd_load` (dead_code): Investigator (suggest): It may be used in ways the code graph can't see (dynamic use or a framework callback).
- `shopcart/commands.py::cmd_total` (dead_code): Investigator (suggest): It may be used in ways the code graph can't see (dynamic use or a framework callback).
- `shopcart/storage.py::load_legacy` (security): Possible security problem: Use of possibly insecure function - consider using safer ast.literal_eval.
- `reproduce_bug.py::L6-6` (debug_leftover): A print in library code; it may be leftover debugging or intended output.
