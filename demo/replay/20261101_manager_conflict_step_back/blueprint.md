# Cleanup blueprint: conflict

A Python project with 7 Python files.

Mode: safe. 2 work packages, applied one at a time; each is tested and checked, then kept as one commit, repaired, or rolled back.

## P1: Remove 1 leftover file in pkg2/colors_old.py

- Risk tier: 1
- Files: pkg2/colors_old.py
- Edits:
  - delete_file `pkg2/colors_old.py` (leftover_file): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes, public_api; related tests: the full suite
- Rollback: reset the workspace to the checkpoint before P1; later packages are unaffected

## P2: Remove 1 leftover file in pkg2/shapes_old.py

- Risk tier: 1
- Files: pkg2/shapes_old.py
- Edits:
  - delete_file `pkg2/shapes_old.py` (leftover_file): Investigator (safe): No evidence that it is still used; the checks after the edit will confirm.
- Verify: compile, tests, probes, public_api; related tests: the full suite
- Rollback: reset the workspace to the checkpoint before P2; later packages are unaffected
