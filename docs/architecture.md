# CleanSweep architecture

CleanSweep removes leftover and over-engineered code from a Python project and keeps an edit
only when the program still behaves the same. This page describes the code as it is: the
pipeline, what each package does, the interfaces between packages, and the settings.

## Pipeline

```
target ──▶ open workspace ──▶ analyze ──▶ plan (Reviewer) ──▶ rank ──▶ batch (Scheduler)
                                                                          │
report ◀── hidden checks (evaluation only) ◀── Guard: apply, verify, keep or roll back
```

`cleansweep.workflow.run_sweep(target, cfg, method, seed, on_event=None)` runs one sweep:

1. **Open.** `open_workspace(target, cfg)` copies the target into a scratch git repository
   with a `base` commit. Targets are a local folder, `swebench:<instance>:<agent>` (a
   SWE-bench Docker image with an agent's patch committed on top) or
   `aidev:<owner>/<name>@<sha>` (a `python:3.11` container that installs the project, then
   loses its network before any project code runs).
2. **Analyze.** `build_graph` parses every `.py` file into file, class and function units
   with import and reference edges, entry points and reachability. `extract_features` gives
   each unit the ranker's features.
3. **Plan.** `build_plan` runs the detectors, merges their findings by unit, asks the LLM
   judge about them, and applies the policies. Every item lands in one of two lanes:
   **safe** (the Guard may apply it) or **suggest** (reported only).
4. **Rank.** The ranker scores safe items. Unless a trained model is configured, it uses
   category priors.
5. **Batch.** `make_batches` groups safe items by risk tier (formatting and imports first,
   then leftover files and dependencies, then code), at most 8 per batch. Items that might
   be used dynamically go alone.
6. **Guard.** For each batch: checkpoint, apply each edit, then verify. If the checks pass,
   the batch is kept. If they fail, `apply_with_bisection` splits it in half until the bad
   edits are isolated. A single failing edit gets one repair attempt before it is rolled
   back.
7. **Report.** A `SweepReport` holds the plan, one `EditResult` per item, and stats (test
   runs, lines removed, LLM usage, the final diff, and the scope the Reviewer used).

Hidden checks (`cleansweep.eval.run_hidden_checks`) are for evaluation only. They run tests
the Guard never sees on the base and on the final diff, in a fresh workspace.

### What the Guard checks

| Step | Fails when |
|---|---|
| compile | a changed file no longer compiles or imports |
| tests | a test fails that passed at baseline (the baseline runs once when the Guard starts) |
| dependency | a removed package is needed: the tests are rerun with it uninstalled, unless another installed package still requires it. Workspaces that can't uninstall mark the removal "checked statically only" |
| AST | a formatting-only batch changes the syntax tree |
| probes | differential probes find a difference: LLM-written calls to the changed functions, run before and after the edit on the same inputs |

Probes run as a script (`direct`) or inside the project's own test command (`runner`, the
default for SWE-bench and AIDev, so they get the project's setup).

## Packages

| Package | Role |
|---|---|
| `core` | Data contracts (`models.py`: `CodeUnit`, `CleanupItem`, `CleanupPlan`, `EditResult`, `RunResult`, `SweepReport`, `CommitEvent`), JSON input and output, config loading, the stub registry, and the interface table (`contracts.py`) |
| `llm` | `LLMClient`, an OpenAI-compatible chat client with a SQLite response cache, retries for rate limits, server errors and dropped connections, and JSON replies (`chat_json`). `FakeLLM` serves tests |
| `sandbox` | `Workspace` (checkpoint, rollback, diff, apply a patch, run tests with a JUnit report, coverage) and its local, SWE-bench and AIDev variants. `hide_packages` / `restore_packages` let the Guard run tests without a removed dependency |
| `analysis` | Code graph (`build_graph`, `CodeGraph`: callers, callees, reachability, `dynamic_risk`, `framework_callback`), framework conventions (`frameworks.py`), duplicate finding, features, and the agent scope (`scope.py`: what an agent wrote, from its patch commit or from git blame over agent commits) |
| `reviewer` | Detectors: leftover files, dead code (vulture, checked against the graph), unused imports, unused dependencies, security, formatting, one-use wrappers, duplicates. Also the LLM judge, the over-engineering review (report only), deterministic rewrites for duplicates and wrappers, the repair prompt, the planner and its policies |
| `guard` | `apply_edit` for every action (delete a file or unit, remove an import or dependency, format, merge a duplicate, inline a wrapper), the `Guard`, and the differential probes (`difftest.py`, `probe_harness.py`) |
| `scheduler` | Batching and bisection, sweep policies (`should_sweep`: daily, after each agent PR, every n commits, adaptive) and the history replay (`simulate`) |
| `ranking` | `Ranker` (category priors or a trained model) and its training |
| `workflow` | `run_sweep` and its optional event callback; `method="agentic"` hands the target to the agent team |
| `agents` | v2 agent team (`docs/agentic_design.md`): the Manager's phase machine (`phases.py`, `manager.py`), the message board (`board.py`), the artifact cache (`cache.py`), budgets, the event log (schema v2, `events.py`), the secret scan and redactor (`secrets.py`), the one LLM door that redacts and charges every request (`llm.py`), the JSON ReAct protocol (`protocol.py`), the tool registry over existing code (`tools.py`), lessons, the knowledge base over the mined tables, the ten agents, the LangGraph team (`team.py`), delivery of the branch (`delivery.py`) and the entry points `run_agentic` and `clean_project` (`run.py`). `ScriptedLLM` plays scripted replies in tests |
| `eval` | Baselines (`tools_only`, `one_shot_llm`, `one_shot_retry`), hidden checks, mutation testing, metrics and statistics (bootstrap intervals, exact McNemar, Wilcoxon) |
| `data` | Loaders for SWE-bench Verified, PatchDiff agent patches and hidden tests, the AIDev repositories and their histories, and the tier splits |
| `mining` | Review-comment mining: removal requests (keyword filter plus an LLM check), their taxonomy (TF-IDF and k-means), and association rules |
| `app` | CleanSweep Studio (`cleansweep studio`), which replaced the Streamlit dashboard: saved reports, live sweep and replay (local recordings in `results/raw/live/`, plus the ones that ship in `demo/replay/`), Scheduler, baselines, data and Guard screens, and the v2 screens |

Each package can be swapped for its stub with `CLEANSWEEP_STUBS=<package>[,<package>]` (or
`all`), so one package can be developed while another is unfinished.

## Lanes and policies

The detectors set a lane per item. The judge then runs in one of three modes:

- **gatekeeper** (default): "suggest" and "keep" move an item to the suggest lane;
- **advisory**: the judge only adds its reason, and the Guard decides;
- **off**: no judge.

Security findings always stay in the suggest lane. Two policies run after the judge:

- `keep_public_api` (auto): dead code on a public name in an importable package module
  goes to the suggest lane when the project has packaging metadata. With no caller in the
  project, the Guard has nothing to run, and only the owner knows whether outside code uses
  it.
- `framework_callbacks` (on): dead code and duplicates on methods a framework calls by name
  go to the suggest lane. Examples are Textual's `compose` and `on_*`, Django's
  `get_queryset`, and Click's `invoke`. The conventions are one table in
  `analysis/frameworks.py`, covering Textual, Django, Flask, FastAPI/Starlette, Click/Typer,
  pytest, the standard library's `http.server` handlers (`do_*`, `log_message`) and
  `ast.NodeVisitor` (`visit_*`), PyTorch and Lightning modules (`forward`, `training_step`,
  `on_*`) and hatchling build hooks (`initialize`).

Format items and format edits run `ruff format` with the project's own ruff settings when it
has them (`ruff.toml`, `.ruff.toml` or `[tool.ruff]` in `pyproject.toml`), and with ruff's
defaults otherwise, so detection and the edit always agree.

## Interfaces

`core/contracts.py` lists the public names and parameters every package (real and stub) must
expose. `scripts/tools/check_contracts.py` checks them. Changes are additive: new parameters are
optional. The main ones:

| Interface | Notes |
|---|---|
| `run_sweep(target, cfg, method="cleansweep", seed=0, on_event=None)` | methods: `cleansweep`, `guard_tests_only` (no probes), `tools_only`, `one_shot_llm`, `one_shot_retry`, `no_ranker`, `no_batching`. `on_event(name, payload)` is called after each step (`open`, `analyze`, `plan`, `rank`, `batch`, `baseline`, `guard`, `report`) and around each Guard check (`check_start`, `check`) |
| `build_plan(workspace, graph=None, llm=None, use_llm=True, cfg=None)` | the run's `reviewer` config section replaces `configs/reviewer.yaml` |
| `judge_items(items, repo_dir, llm, batch_size=None, mode=None, graph=None, cfg=None)` | every item stays in the plan; the mode decides lanes |
| `Guard(workspace, llm, cfg, repair_fn=None, graph=None)` | `check_batch(items) -> bool`, `results()` |
| `CodeGraph.framework_callback(unit_key)` | the framework that calls a method by name, or `None` |
| `run_hidden_checks(target, final_diff, cfg)` | hidden tests before and after the diff |

## Configuration

Settings come from four YAML files in `configs/` (`base.yaml` holds `core`, plus
`reviewer.yaml`, `exp.yaml` and `data.yaml`) and from a `.env` file that is never committed.
A sweep's `cfg` is the merged dictionary; a caller can override any section.

| Setting | Default | Meaning |
|---|---|---|
| `core.llm.enabled` | `auto` | use the LLM only when an API key is set |
| `core.llm.timeout_s`, `max_retries` | 600, 2 | per request |
| `core.llm.cache_path` | `.cleansweep/llm_cache.sqlite` | response cache |
| `core.sandbox.work_dir` | system temp | where workspaces are created |
| `core.guard.diff_tests` | true | run differential probes |
| `core.guard.probe_mode` | `auto` | `direct`, `runner`, or runner for containers and direct for folders |
| `core.guard.max_targets`, `probe_max_cases` | 10, 8 | probe budget per batch |
| `core.guard.repair` | true | one repair attempt per failing edit |
| `reviewer.judge_mode` | `gatekeeper` | `gatekeeper`, `advisory`, `off` |
| `reviewer.scope` | `auto` | `agent` (only what the agent wrote), `repo`, or agent for SWE-bench and AIDev targets |
| `reviewer.keep_public_api` | `auto` | `on`, `off`, `auto` |
| `reviewer.framework_callbacks` | `on` | `on`, `off` |
| `reviewer.exclude` | `[]` | path prefixes the Reviewer leaves alone (detectors and the over-engineering review) |
| `reviewer.vulture_min_confidence`, `duplicate_threshold` | 60, 0.8 | detector thresholds |
| `reviewer.overengineering` | true | the over-engineering review (report only) |
| `exp.batch_max_size` | 8 | Guard batch size |
| `exp.ranker_path` | unset | a trained ranker model; priors otherwise |
| `exp.hidden_alt_cache` | `.cleansweep/hidden_tests` | AIDev second-model hidden tests, generated once per target |

| Environment variable | Meaning |
|---|---|
| `VOYAGER_API_KEY`, `VOYAGER_BASE_URL` | the OpenAI-compatible endpoint |
| `VOYAGER_MODEL` | judge, repair, probes and the one-shot baseline |
| `VOYAGER_MODEL_ALT` | a second model for the AIDev hidden tests, kept independent of the Guard |
| `CLEANSWEEP_JUDGE_MODE` | overrides `reviewer.judge_mode` |
| `CLEANSWEEP_OVERENGINEERING` | `0` turns the over-engineering review off |
| `CLEANSWEEP_STUBS` | packages to replace with their stubs |

## Command line

```
python -m cleansweep plan  --target PATH            # the plan, nothing applied, no LLM
python -m cleansweep sweep --target T [--method M] [--out report.json] [--hidden]
python -m cleansweep show  report.json
python -m cleansweep clean PATH [--mode safe|thorough] [--budget llm=N,minutes=N,tests=N]
                                [--approve-plan] [--dry-run] [--out DIR] [--model M] [--no-llm]
python -m cleansweep studio [--port N] [--runs DIR] [--no-browser]
```

The experiment scripts in `scripts/` are described in `docs/experiments.md`.

## Limitations

- The Guard can only see behavior that something runs. Deleting a function nothing in the
  project calls changes nothing it can observe. That is why public API and framework
  callbacks go to the suggest lane.
- Probes test only the inputs the model thinks of.
- Duplicate merges and wrapper inlining rewrite uses in the same file only; other cases are
  suggested.
- Duplicate finding compares all pairs, which is fine for one agent's changes and slow for a
  whole large repository.
- The Scheduler replay uses the static detectors at sampled commits and estimates test runs.
- Dependency removals are verified by uninstalling only in AIDev containers; elsewhere they
  are "checked statically only".
- Format edits follow ruff's settings, not those of other formatters.
