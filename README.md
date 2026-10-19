# CleanSweep

Coding agents write code quickly but rarely clean up after themselves. They leave behind
scratch scripts, old copies of files, helpers that duplicate ones the project already has,
and wrappers nobody needs. Removing that code by hand is risky: a careless cleanup can
delete something that is still used, and the project's own tests often won't notice.

CleanSweep cleans a Python project without changing what it does. A **Reviewer** finds
code that can go, a **Guard** applies each edit and keeps it only if the program still
behaves the same, and a **Scheduler** decides how to batch edits (and, later, when to
sweep). This is our CSE 572 project (Group 30).

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
pytest -q
python scripts/check_contracts.py
```

For LLM features, put your Voyager settings in `.env` (never commit it):

```
VOYAGER_API_KEY=...
VOYAGER_BASE_URL=https://openai.rc.asu.edu/v1
VOYAGER_MODEL=...
VOYAGER_MODEL_ALT=...
```

Without a key, the sweep runs fully offline (static detectors, no LLM judge or repair).

## Usage

```bash
# show what the Reviewer would remove, without changing anything
python -m cleansweep plan --target tests/fixtures/toy_repo

# run a sweep, save the report, and score it with the hidden checks
python -m cleansweep sweep --target tests/fixtures/toy_repo --out /tmp/report.json --hidden

# baselines and ablations use the same command
python -m cleansweep sweep --target tests/fixtures/toy_repo --method tools_only --hidden

# print a saved report
python -m cleansweep show /tmp/report.json

# dashboard (reads results/raw/, falls back to the sample report)
streamlit run app/dashboard.py
```

Methods: `cleansweep`, `guard_tests_only`, `tools_only`, `one_shot_llm`, `no_ranker`,
`no_batching`.

If a teammate's package is broken or not merged yet, switch it to its stub:

```bash
CLEANSWEEP_STUBS=analysis,guard python -m cleansweep sweep --target tests/fixtures/toy_repo
CLEANSWEEP_STUBS=all python -m cleansweep sweep --target tests/fixtures/toy_repo
```

## Baseline results on the toy repo

The toy repo (`tests/fixtures/toy_repo`) is a small shopping-cart package with 13
planted problems, including two traps: a command that is only reached through `getattr`,
and a rounding helper that looks like a duplicate but rounds .5 differently. The hidden
checks in `tests/fixtures/toy_repo_hidden` are never shown to the Guard.

| Method | Edits kept | Test runs | Visible tests broken | Hidden checks changed |
|---|---|---|---|---|
| `cleansweep` (Guard uses tests only for now) | 11 | 4 | 0 | yes (near-duplicate trap) |
| `tools_only` | 7 | 0 | 2 | yes |
| `no_batching` | 11 | 12 | 0 | yes |

The near-duplicate trap passes every existing test, so the tests-only Guard keeps it.
Catching it is the job of the differential probes, which are the next Guard task.

## Repository layout

```
src/cleansweep/
  core/        contracts (models.py), config, JSON io, stub switch
  llm/         Voyager client with disk cache, FakeLLM for tests
  sandbox/     git-backed workspaces (local now; SWE-bench/AIDev Docker next)
  guard/       applies edits, verifies them, rolls back failures
  workflow/    run_sweep: open -> analyze -> plan -> rank -> batch -> guard -> report
  analysis/    code graph, duplicate finder, features
  reviewer/    detectors, duplicate/wrapper rewrites, LLM judge and repair, planner
  ranking/     safe-to-remove scores (category priors until the classifier is trained)
  scheduler/   batching with bisection, sweep policies
  eval/        baselines, hidden checks, metrics
  data/ mining/  dataset loaders and comment mining (stubs for now)
app/           Streamlit dashboard
configs/       base.yaml (core), data.yaml, exp.yaml, reviewer.yaml
scripts/       check_contracts.py, voyager_ping.py, core_make_samples.py
tests/         one folder per package, plus fixtures/ (toy repo, sample report)
```

## Team

| Member | Role |
|---|---|
| Ritik Agarwal | Project manager, UI lead, Reviewer |
| Badri Sri Vaishnavi Yeluri | Data architect |
| Simran Sharma | Experiment architect |
| Maninderjit Singh Bhullar | Software architect |
