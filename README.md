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

### SWE-bench Tier 1

Ten plausible agent patches from SWE-bench Verified (PatchDiff's three agents, 4 instances:
`pytest-dev__pytest-10081`, `django__django-11095`, `sympy__sympy-11618` × 3 agents, and
`pydata__xarray-3151` × 1; 3 of the 10 behave differently from the developer's fix). Each runs in
its prebuilt SWE-bench Docker image (emulated amd64 on an arm64 laptop). On these targets the
Reviewer looks only at what the agent's patch wrote (`reviewer.scope`), and so does the
tools-only baseline. Hidden checks run in a fresh container: the instance's FAIL_TO_PASS and
PASS_TO_PASS tests plus PatchDiff's generated tests for that patch (1 to 38 stable tests per
patch), which the Guard never sees. 2026-10-26, judge `qwen36-35b-a3b`,
`scripts/exp_swebench.py --tier data/splits/swebench_tier1.json --out results/raw/swebench_t1`.

| Method | Items found | Edits applied | Files removed | Lines removed | Rolled back | Test runs | Hidden changed | Min per patch |
|---|---|---|---|---|---|---|---|---|
| `cleansweep`, gatekeeper | 20 leftover files | 20 | 20 | 570 | 0 | 48 | 0/10 | 2.2 |
| `cleansweep`, advisory (with probes) | 20 leftover files | 20 | 20 | 570 | 0 | 48 | 0/10 | 1.8 |
| `guard_tests_only` (advisory) | 20 leftover files | 20 | 20 | 570 | 0 | 48 | 0/10 | 1.8 |
| `tools_only` | vulture + ruff | 8 | 0 | 18 | n/a | 30 | 0/10 | 1.2 |

What the agents left behind: reproduction scripts (`reproduce_error.py`, `reproduce.py`,
`edge_cases.py`) in 5 of the 10 patches (all four CodeStory patches and one LearnByInteract
patch), scratch tests at the repo root (3 files in one OpenHands patch), and a whole throwaway
Django project (`test_app/` plus two root scripts, 11 files in one OpenHands patch). In the
agent-written code itself the detectors found no dead code, unused imports or duplicates on these
10 patches. Three patches left nothing to clean.

- No method changed the hidden behavior of any patch; nothing was rolled back.
- The probes were hardly exercised: 18 of 20 batches only deleted files nothing imports, so there
  was nothing to call (one batch ran 23 cases, all equal). `guard_tests_only` therefore gives the
  same result as advisory here.
- Gatekeeper mode now applies all 20 files. Before the fix for issue #26 it applied 12: the judge
  held back 8 of the 11 Django scratch files because its signals counted an "import" from another
  scratch file, a bare file name like `admin` in Django's config, and strings in scratch files as
  dynamic use. For files the agent created, the signals now count only project code.
- `tools_only` removes unused imports from the scratch files and reformats them instead of deleting
  them.
- Cost: 14 live LLM calls (about 23k prompt and 46k completion tokens) for the first method on each
  patch, plus 8 for the gatekeeper rerun after #26; the other methods were answered from the
  cache. The hidden checks add about 0.9 minutes
  per patch. Tables: `docs/report/tables/swebench_tier1*.md`.

### SWE-bench Tier 2 (running)

60 PatchDiff patches (21 instances from 11 repositories; 18 patches behave differently from the
developer's fix) × 5 methods, `scripts/exp_swebench.py --tier data/splits/swebench_tier2.json`, in a
frozen clone of main (started 2026-10-26 15:08). **At the last check 109 of 300 runs were done
(22 patches).** Numbers below are for those 22 patches and will change.

- `cleansweep` (both judge modes) and `guard_tests_only` applied the same 36 edits on 18 of 22
  patches, all leftover files the agent created (1,012 lines), with 0 rollbacks. `tools_only`
  made 23 small edits (unused imports, 1 dead-code item; 24 lines). `one_shot_llm` applied
  nothing: its diffs don't apply.
- Hidden behavior changed in 1 run of 109: `sympy__sympy-11618`/CodeStory under
  `guard_tests_only`. The same two edits were applied under `cleansweep` (advisory and
  gatekeeper), and there the hidden check saw no change. So this is a flaky PatchDiff test
  (`test_polygon_perimeter_patch1`) that passed the two-run stability check, not something the
  probes caught.
- Minutes per patch (median): gatekeeper 2.0, advisory 1.2, `guard_tests_only` 1.4,
  `tools_only` 0.7, `one_shot_llm` 1.6. The gatekeeper mean in the table below includes one
  Django run that took 197 minutes because the laptop slept.

### Main table

Mean per target and 95% bootstrap CI (2,000 resamples). "Answer keys" pools the toy repo and the
demo app (one target each). `scripts/exp_collect.py` then `scripts/exp_tables.py`; files in
`results/summary/` (`main_table.md`, `paired_tests.md`, `ablation.md`).

| target set | method | n | lines removed | edits | hidden changed | test runs | minutes |
|---|---|---|---|---|---|---|---|
| answer keys | cleansweep, gatekeeper | 2 | 48.5 [47.0, 50.0] | 7.5 [5.0, 10.0] | 0.00 [0.00, 0.00] | 4.5 | 0.1 |
| answer keys | cleansweep, advisory | 2 | 48.5 [47.0, 50.0] | 7.5 [5.0, 10.0] | 0.00 [0.00, 0.00] | 8.0 | 0.1 |
| answer keys | `guard_tests_only` | 2 | 57.5 [56.0, 59.0] | 8.5 [6.0, 11.0] | 1.00 [1.00, 1.00] | 4.5 | 0.1 |
| answer keys | `tools_only` | 2 | 50.5 [38.0, 63.0] | 9.0 [7.0, 11.0] | 1.00 [1.00, 1.00] | 0.0 | 0.0 |
| answer keys | `one_shot_llm` | 2 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.00 [0.00, 0.00] | 0.0 | 0.6 |
| SWE-bench Tier 1 | cleansweep, gatekeeper | 10 | 57.0 [13.3, 122.9] | 2.0 [0.6, 4.1] | 0.00 [0.00, 0.00] | 4.8 | 2.2 |
| SWE-bench Tier 1 | cleansweep, advisory | 10 | 57.0 [13.3, 122.9] | 2.0 [0.6, 4.1] | 0.00 [0.00, 0.00] | 4.8 | 1.8 |
| SWE-bench Tier 1 | `guard_tests_only` | 10 | 57.0 [13.3, 122.9] | 2.0 [0.6, 4.1] | 0.00 [0.00, 0.00] | 4.8 | 1.8 |
| SWE-bench Tier 1 | `tools_only` | 10 | 1.8 [0.0, 4.2] | 0.8 [0.4, 1.2] | 0.00 [0.00, 0.00] | 3.0 | 1.2 |
| SWE-bench Tier 1 | `one_shot_llm` | 10 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.00 [0.00, 0.00] | 3.0 | 3.4 |
| SWE-bench Tier 2 (partial) | cleansweep, gatekeeper | 22 | 46.0 [24.0, 79.6] | 1.6 [1.0, 2.7] | 0.00 [0.00, 0.00] | 4.9 | 11.3 |
| SWE-bench Tier 2 (partial) | cleansweep, advisory | 22 | 46.0 [24.0, 79.6] | 1.6 [1.0, 2.7] | 0.00 [0.00, 0.00] | 4.9 | 1.9 |
| SWE-bench Tier 2 (partial) | `guard_tests_only` | 22 | 46.0 [24.0, 79.6] | 1.6 [1.0, 2.7] | 0.05 [0.00, 0.14] | 4.9 | 1.9 |
| SWE-bench Tier 2 (partial) | `tools_only` | 22 | 1.1 [0.1, 2.3] | 0.9 [0.7, 1.1] | 0.00 [0.00, 0.00] | 3.0 | 1.9 |
| SWE-bench Tier 2 (partial) | `one_shot_llm` | 21 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.00 [0.00, 0.00] | 3.0 | 1.8 |

Paired against cleansweep in gatekeeper mode on SWE-bench:

- No method differs on hidden changes (exact McNemar p = 1.0 everywhere).
- `tools_only` and `one_shot_llm` remove fewer lines (Wilcoxon p = 0.016 on Tier 1; p = 0.0002 and 0.0003 on Tier 2 so far).
- On the answer keys, the probes and the judge each keep the hidden checks unchanged where `guard_tests_only` and `tools_only` change them (0/2 vs 2/2). On SWE-bench, both modes and `guard_tests_only` apply the same edits.

### Guard strength

How often `verify` (tests, then probes) rejects a change that should be rejected
(`scripts/exp_guard_strength.py`, `results/summary/guard_strength.csv`, 2026-10-26).

| Target | Experiment | n | Caught | By tests | Only by probes |
|---|---|---|---|---|---|
| toy repo | mutants in package functions | 20 | 20 | 13 | 7 |
| demo app | mutants in package functions | 20 | 18 | 16 | 2 |
| SWE-bench Tier 1 | mutants in agent-written functions (≤5 per patch) | 39 | 30 | 30 | 0 |
| SWE-bench Tier 1 | PatchDiff recall: agent patch vs developer fix (differs) | 3 | 0 | 0 | 0 |
| all | false alarms on identical copies (probes on touched functions) | 12 | 0 | | |

Mutants use 5 operators: flip a comparison, swap + and -, add 1 to an int constant, swap
and/or, return None. On the answer keys, the probes catch a third of the mutants that the
tests miss. On Tier 1 they catch none, because they can't import Django admin modules without
settings, and the agents' own changes are small. The Guard didn't tell any of the 3 differing
agent patches apart from the developer's fix: the visible tests pass for both, and the probes
found no input that separates them.

### AIDev: Scheduler replay, ranker and Reviewer detection

AIDev-pop (`data/raw/aidev/`): 666 Python repositories with ≥10 merged agent PRs; a seeded
sample of 120. A repository is kept if it installs in `python:3.11` (network cut before tests)
and runs ≥5 tests with ≥90% passing in under 10 minutes: **21 of 120**. The committed files
list 20 (see `results/data_summary/aidev_filter.csv` for the drop reasons). The replay uses
each repository's last 300 first-parent commits (4,695 in total, 626 from agent PRs) and the
static detectors, measured at up to 40 commits per repository (`scripts/exp_replay.py`; the
dashboard's Scheduler page shows the curves).

| Policy | Median slop-debt reduction vs. never sweeping | Sweeps | Test runs (est.) | Resurrection rate (mean) |
|---|---|---|---|---|
| after every agent PR | 68.8% | 95 | 314 | 0.19 |
| every 5 commits | 54.2% | 67 | 237 | 0.15 |
| daily (UTC, at the day boundary) | 95.2% | 190 | 554 | 0.22 |
| adaptive (slop > 2% of lines) | 33.9% | 20 | 142 | 0.17 |

Daily sweeps keep slop lowest but cost 1.8× the test runs of sweeping after every agent PR, and
more of what they remove comes back. The resurrection rate is the share of removed functions,
classes and imports that still exist at the last commit and are no longer flagged, because a
later commit started using them.

**Removal requests.**
- Mining: 6,330 human review comments on .py files → 792 keyword matches → **535 removal requests** confirmed by the LLM. They come from 102 repositories, most often about dead code (224).
- Taxonomy: 15 clusters. Rules: 64 with lift ≥ 1.2 (`results/data_summary/`).
- The runnable repositories have almost no human review, so labels come from all repositories with a request: **9,416 units, 262 removal requests, 79 repositories** (static analysis only).

**Ranker.**
- Calibrated gradient boosting, cross-validated by repository: out-of-fold AUC 0.61, Brier 0.027 (`results/summary/ranker_cv.csv`, `results/figures/ranker_reliability.png`).
- It predicts which units reviewers ask to remove, not which edits are safe, so the Reviewer keeps its category priors by default (`exp.ranker_path` switches it on).

**Reviewer detection vs. those requests.**
- Precision 0.024, recall 0.075 (19 of 253 requested units, `results/summary/reviewer_detection.csv`).
- Reviewers mostly ask to remove lines inside a function (comments, try/except blocks, assertions), which the unit-level detectors don't look for.

## Repository layout

```
src/cleansweep/
  core/        contracts (models.py), config, JSON io, stub switch
  llm/         Voyager client with disk cache, FakeLLM for tests
  sandbox/     git-backed workspaces: local folders, SWE-bench and AIDev Docker containers
  guard/       applies edits, verifies them (tests, AST, differential probes), rolls back failures
  workflow/    run_sweep: open -> analyze -> plan -> rank -> batch -> guard -> report
  analysis/    code graph, duplicate finder, features
  reviewer/    detectors, duplicate/wrapper rewrites, LLM judge, over-engineering review, repair, planner
  ranking/     safe-to-remove scores (category priors; a classifier trained on AIDev labels)
  scheduler/   batching with bisection, sweep policies, history replay
  eval/        baselines, hidden checks, metrics, mutation testing, statistics
  data/        SWE-bench Verified, PatchDiff and AIDev loaders, tier splits
  mining/      review-comment mining: removal requests, taxonomy, rules
app/           Streamlit dashboard, Live sweep and Scheduler pages, step-by-step live runner
demo/          bookstore demo app, answer key, hidden tests, feature patch, demo script
configs/       base.yaml (core), data.yaml, exp.yaml, reviewer.yaml
scripts/       contract check, data fetch/splits, AIDev selection and mining, experiment runners and tables
tests/         one folder per package, plus fixtures/ (toy repo, answer key, hidden tests, sample report)
```

## Team

| Member | Role |
|---|---|
| Ritik Agarwal | Project manager, UI lead, Reviewer |
| Badri Sri Vaishnavi Yeluri | Data architect |
| Simran Sharma | Experiment architect |
| Maninderjit Singh Bhullar | Software architect |
