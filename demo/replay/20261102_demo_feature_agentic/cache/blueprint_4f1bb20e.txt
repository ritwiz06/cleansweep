# Cleanup blueprint: shop_app

A Python project with 16 Python files.

Mode: safe. 6 work packages, applied one at a time; each is tested and checked, then kept as one commit, repaired, or rolled back.

## P1: Remove 1 leftover file in bookshelf/inventory_old.py

- Risk tier: 1
- Files: bookshelf/inventory_old.py
- Edits:
  - delete_file `bookshelf/inventory_old.py` (leftover_file): Investigator (safe): The file is a standalone leftover with no references in code, tests, or configs, and contains no framework-specific callbacks or public APIs.
- Verify: compile, tests, probes, public_api; related tests: the full suite
- Rollback: reset the workspace to the checkpoint before P1; later packages are unaffected

## P2: Remove 1 leftover file in scratch_restock.py

- Risk tier: 1
- Files: scratch_restock.py
- Edits:
  - delete_file `scratch_restock.py` (leftover_file): Investigator (safe): The file scratch_restock.py has no references in code, tests, or configuration files, and its name suggests it is a temporary or debug artifact. It is safe to delete.
- Verify: compile, tests, probes, public_api; related tests: the full suite
- Rollback: reset the workspace to the checkpoint before P2; later packages are unaffected

## P3: Remove 1 unused function or class in bookshelf/inventory.py

- Risk tier: 2
- Files: bookshelf/inventory.py
- Edits:
  - delete_unit `bookshelf/inventory.py::_print_low_stock` (dead_code): Investigator (safe): The function _print_low_stock is a private helper with no callers, no tests, and no dynamic references, making it dead code.
- Verify: compile, tests, probes, public_api; related tests: tests/test_cli.py, tests/test_inventory.py, tests/test_lowstock.py, tests/test_orders_reports.py
- Rollback: reset the workspace to the checkpoint before P3; later packages are unaffected

## P4: Remove 1 duplicate in bookshelf/orders.py

- Risk tier: 2
- Files: bookshelf/orders.py
- Edits:
  - replace_with `bookshelf/orders.py::_round_money` (duplicate): Investigator (safe): _round_money is a near-duplicate of round_money in utils.py and is only used internally by order_total; replacing it with the shared utility is safe.
- Verify: compile, tests, probes; related tests: tests/test_orders_reports.py
- Rollback: reset the workspace to the checkpoint before P4; later packages are unaffected

## P5: Remove 1 duplicate in bookshelf/reports.py

- Risk tier: 2
- Files: bookshelf/reports.py
- Edits:
  - replace_with `bookshelf/reports.py::_clean_isbn` (duplicate): Investigator (safe): _clean_isbn is an exact duplicate of normalize_isbn and is only called internally by stock_line, so it can be safely removed and replaced.
- Verify: compile, tests, probes; related tests: tests/test_orders_reports.py
- Rollback: reset the workspace to the checkpoint before P5; later packages are unaffected

## P6: Remove 1 unused function or class in bookshelf/utils.py

- Risk tier: 2
- Files: bookshelf/utils.py
- Edits:
  - delete_unit `bookshelf/utils.py::isbn_checksum_ok` (dead_code): Investigator (safe): The function isbn_checksum_ok is not referenced in code, tests, or dynamically, and is not part of any public API. It is dead code.
- Verify: compile, tests, probes, public_api; related tests: tests/test_utils.py
- Rollback: reset the workspace to the checkpoint before P6; later packages are unaffected

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
