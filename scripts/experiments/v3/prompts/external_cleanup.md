Clean up leftover slop in this Python project without changing what it does.

Remove only what is clearly unused or left over:
- leftover files: scratch, temporary, backup or experiment files that nothing imports, runs or
  refers to;
- dead code: functions, classes, methods and module-level variables that nothing uses;
- duplicate code: when two functions are exact copies, keep one and make the other place use it;
- unused imports;
- unused dependencies: packages listed in pyproject.toml, setup.py, setup.cfg or requirements
  files that the project never imports;
- debug leftovers: debug prints (such as `print(f"{value=}")`) and debugger calls
  (`breakpoint()`, `pdb.set_trace()`);
- commented-out code (keep comments that explain something).

Rules:
- Do not change behavior. Every module, function and class that stays must work exactly as
  before for its callers.
- Make only mechanical removals. Do not refactor, rename, reformat, add features or rewrite code
  that is not slop.
- When you are not sure that something is unused or left over, leave it alone. In particular,
  keep:
  - code that may be called by name or dynamically: framework callbacks and hooks (such as the
    `visit_*` methods of an `ast.NodeVisitor`, `on_*` handlers, plugin entry points), and names
    used through `getattr`, `importlib`, strings, decorators or registries;
  - functions that look alike but differ in any detail (near-duplicates);
  - the public API: names exported in `__init__.py` or `__all__`, documented, or meant to be
    imported by users of the package;
  - prints that are the program's intended output (command-line tools, scripts);
  - tests, test fixtures and test data.
- Do not edit tests to make them pass.
- Run the project's tests after your changes. They must pass as they did before you started;
  undo any change that makes a test fail.
