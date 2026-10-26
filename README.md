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

## Judge

When a Voyager key is set, an LLM judge reads every item the detectors found, with its code
and evidence, and gives a decision, a short reason and a confidence. It never drops an item.
It has three modes, set in `configs/reviewer.yaml` (`judge_mode`) or per run with an
environment variable:

| Mode | What the judge's decision does |
|---|---|
| `gatekeeper` (default) | "suggest" or "keep" moves the item to the suggest lane, so it is reported but not applied |
| `advisory` | only the reason and confidence are recorded; the detectors' lanes stay and the Guard decides |
| `off` | the judge is skipped |

```bash
CLEANSWEEP_JUDGE_MODE=advisory python -m cleansweep sweep --target tests/fixtures/toy_repo --hidden
```

Formatting items skip the judge (the Guard checks that the code structure is unchanged), and
security items always stay in the suggest lane.

After the judge, a second prompt looks for over-engineering: extra checks, needless
abstractions, unused parameters and defensive code for cases that can't happen. Its findings
are only reported (suggest lane). It sees up to three test lines that call each function,
and a "can't happen" finding is dropped when a test runs those lines (one coverage run per
sweep). Turn it off in `configs/reviewer.yaml` (`overengineering: false`) or for one run with
`CLEANSWEEP_OVERENGINEERING=0`.

The judge model is `VOYAGER_MODEL` in `.env` (we use `qwen36-35b-a3b`). `VOYAGER_MODEL_ALT` is
reserved for LLM-written hidden checks, which are not built yet.

## Guard

The Guard applies each batch of safe edits and keeps it only if nothing changed: the changed
files compile, the packages import, the project's tests give the same results as before, and
formatting-only batches leave the AST unchanged. For every other batch it then runs
**differential probes**: the LLM writes small calls (edge cases such as .5 ties, zero, negative
numbers, empty values and `None`) for the functions the batch changed and their callers, and
our harness runs them on the code before (twice, to drop unstable cases) and after the edit.
A removed duplicate or wrapper is also run against the code that replaces it, on the same
inputs. Each changed module must still import and keep its public names. Any difference rolls
the batch back, and a failing batch is split in half until the bad edit is found. Probes are
cached by the source of the function they call, so a rerun asks the LLM nothing new.

Settings are under `core.guard` in `configs/base.yaml` (`diff_tests`, `max_targets` and the
`probe_*` keys). The `guard_tests_only` method turns the probes off.

## Demo

`demo/shop_app` is a small bookstore inventory app with 11 tests and 7 planted problems.
`demo/feature.patch` is the kind of change a coding agent makes: a new `lowstock` command
that also leaves a helper behind. The timed script is in `demo/run_demo.md`.

```bash
bash demo/prepare_demo.sh --with-feature   # builds .cleansweep/demo/shop_app as a git repo
streamlit run app/dashboard.py             # then open the "Live sweep" page
```

On **Live sweep**, pick a target (toy repo, prepared demo, `demo/shop_app` or any path), a
method and a judge mode, and press **Run**. The page shows each stage as it finishes, the
Reviewer's plan, one card per Guard check (including bisection splits), the diffs, the
hidden-check verdict, the score against the answer key, and the run log. Every run is saved
under `results/raw/live/<run_id>/`, and **Replay** plays a saved run back at 1–50x without
calling the LLM or running tests. To record a run without the browser:

```bash
python -m app.live_runner --target .cleansweep/demo/shop_app --judge-mode advisory
```

## Results

Both test targets have an answer key (`tests/fixtures/toy_repo_expected.json`,
`demo/shop_app_expected.json`) and hidden tests the Guard never sees
(`tests/fixtures/toy_repo_hidden`, `demo/shop_app_hidden`). The toy repo has 13 planted
problems and the demo app 7. Each has two traps: a command that is only reached through
`getattr`, and a rounding helper that looks like a duplicate but rounds .5 differently.

**Methods on the toy repo** (judge `qwen36-27b`, 2026-10-24):

| Run | Kept | Test runs | Visible broken | Hidden changed |
|---|---|---|---|---|
| `cleansweep`, judge off (`CLEANSWEEP_JUDGE_MODE=off`) | 11 | 4 | 0 | yes (1 hidden test fails) |
| `cleansweep`, judge in gatekeeper mode | 10 | 4 | 0 | no |
| `cleansweep`, judge in advisory mode | 11 | 4 | 0 | yes (1 hidden test fails) |
| `tools_only` | 7 | 0 | 2 | yes (2 hidden tests fail) |
| `no_batching`, judge in gatekeeper mode | 10 | 11 | 0 | no |

**Replay recordings** (judge `qwen36-35b-a3b`; the demo runs have `feature.patch` applied):

| Recording | Kept | Test runs | Hidden changed | Outcome vs. answer key |
|---|---|---|---|---|
| `20261024_toy_gatekeeper` | 10 | 4 | no | 13/13 |
| `20261024_toy_advisory` | 11 | 4 | yes | 12/13 |
| `20261025_demo_feature_gatekeeper` | 5 | 4 | no | 7/7 |
| `20261025_demo_feature_advisory` | 6 | 4 | yes | 6/7 |

The toy recordings' 4 test runs are 1 baseline and 3 Guard checks. The demo recordings were
made after the over-engineering review was added, so theirs are 1 baseline, 1 coverage run and
2 Guard checks.

**Judge checks.** On the toy repo, `qwen36-35b-a3b`, `kimi-k2-7-code` and `qwen36-27b` (three
runs each, gatekeeper) made the same decisions on every run: every item ended up applied or
not applied as the answer key expects. On the demo app, `qwen36-35b-a3b` and `qwen36-27b`
(one run each) did the same. Request times varied a lot between sessions (about 40 to 260
seconds per judge request), so we don't compare models on speed yet.

In gatekeeper mode the judge keeps the near-duplicate trap out of the edits. Without probes,
advisory mode shows that the Guard can't catch it on its own: every existing test passes, and
only the hidden test notices.

**With differential probes** (2026-10-26, judge `qwen36-35b-a3b`; probe requests with reasoning
off; recordings `20261026_*`):

| Target | Method | Judge mode | Kept | Rolled back by probes | False alarms | Test runs | Hidden changed | Outcome |
|---|---|---|---|---|---|---|---|---|
| toy repo | `cleansweep` | advisory | 10 | 1 | 0 | 9 | no | 13/13 |
| toy repo | `cleansweep` | gatekeeper | 10 | 0 | 0 | 5 | no | 13/13 |
| toy repo | `guard_tests_only` | advisory | 11 | 0 | 0 | 5 | yes | 12/13 |
| demo app + feature | `cleansweep` | advisory | 5 | 1 | 0 | 7 | no | 7/7 |
| demo app + feature | `cleansweep` | gatekeeper | 5 | 0 | 0 | 4 | no | 7/7 |

Now the Guard catches the near-duplicate trap itself: in advisory mode the probes call the
removed helper and the one that replaces it on the same inputs (0.125 gives 0.13 before and
0.12 after) and roll the edit back, so the hidden checks don't change. No safe edit was
blocked. Bisection costs a few extra test runs (9 instead of 4 on the toy repo).

## Repository layout

```
src/cleansweep/
  core/        contracts (models.py), config, JSON io, stub switch
  llm/         Voyager client with disk cache, FakeLLM for tests
  sandbox/     git-backed workspaces (local now; SWE-bench/AIDev Docker next)
  guard/       applies edits, verifies them (tests, AST, differential probes), rolls back failures
  workflow/    run_sweep: open -> analyze -> plan -> rank -> batch -> guard -> report
  analysis/    code graph, duplicate finder, features
  reviewer/    detectors, duplicate/wrapper rewrites, LLM judge, over-engineering review, repair, planner
  ranking/     safe-to-remove scores (category priors until the classifier is trained)
  scheduler/   batching with bisection, sweep policies
  eval/        baselines, hidden checks, metrics
  data/ mining/  dataset loaders and comment mining (stubs for now)
app/           Streamlit dashboard, Live sweep page, step-by-step live runner
demo/          bookstore demo app, answer key, hidden tests, feature patch, demo script
configs/       base.yaml (core), data.yaml, exp.yaml, reviewer.yaml
scripts/       check_contracts.py, voyager_ping.py, core_make_samples.py
tests/         one folder per package, plus fixtures/ (toy repo, answer key, hidden tests, sample report)
```

## Team

| Member | Role |
|---|---|
| Ritik Agarwal | Project manager, UI lead, Reviewer |
| Badri Sri Vaishnavi Yeluri | Data architect |
| Simran Sharma | Experiment architect |
| Maninderjit Singh Bhullar | Software architect |
