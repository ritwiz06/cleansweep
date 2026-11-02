# CleanSweep

Coding agents write code quickly but rarely clean up after themselves. They leave behind
scratch scripts, old copies of files, helpers that duplicate ones the project already has,
and wrappers nobody needs. Removing that code by hand is risky: a careless cleanup can
delete something that is still used, and the project's own tests often won't notice.

CleanSweep cleans a Python project without changing what it does. A **Reviewer** finds
code that can go, a **Guard** applies each edit and keeps it only if the program still
behaves the same, and a **Scheduler** decides how to batch edits and when to
sweep. This is our CSE 572 project (Group 30).

**Results in brief.** On 57 SWE-bench agent patches, CleanSweep removed about as much code as
an unchecked one-shot LLM cleanup and changed hidden behavior on none of them; the one-shot
cleanup changed it on 9. On 20 real repositories with agent-written code, the v1.0 Reviewer
policies leave CleanSweep with 0 of 19 hidden changes. Details below and in
[docs/results.md](docs/results.md).

## Quick start

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
pytest -q -m "not llm and not docker and not network and not slow"   # offline tests
python scripts/tools/check_contracts.py
```

The offline set leaves out the tests marked `llm` (they need the key below), `docker` (a running
Docker), `network` and `slow`; plain `pytest -q` runs them all. It includes chaos tests (an LLM
that is down or answers garbage, a crashed test run, a failing tool, an interrupted run:
`tests/agents/test_chaos.py`) and property tests on seeded generated inputs
(`tests/agents/test_properties.py`, `tests/guard/test_properties.py`).
`bash scripts/tools/coverage.sh` reports the line coverage of `agents/` and `guard/` and fails
under 80%.

For the LLM features, put the settings of an OpenAI-compatible endpoint in `.env` (never commit
it):

```
VOYAGER_API_KEY=...
VOYAGER_BASE_URL=https://<your endpoint>/v1
VOYAGER_MODEL=...          # judge, repair, probes, one-shot baseline
VOYAGER_MODEL_ALT=...      # second model that writes the AIDev hidden tests
```

Without a key, the sweep runs fully offline (static detectors and tests, no LLM judge, repair or
probes).

```bash
# show what the Reviewer would remove, without changing anything
python -m cleansweep plan --target tests/fixtures/toy_repo

# run a sweep, save the report, and score it with the hidden checks
python -m cleansweep sweep --target tests/fixtures/toy_repo --out results/raw/quickstart/report.json --hidden

# baselines and ablations use the same command
python -m cleansweep sweep --target tests/fixtures/toy_repo --method tools_only --hidden

# print a saved report
python -m cleansweep show results/raw/quickstart/report.json

# dashboard (lists the reports under results/raw/, falls back to the sample report)
streamlit run app/dashboard/dashboard.py
```

`results/raw/` is git-ignored, and the dashboard lists every report saved under it. Without a
key, the toy sweep applies the planted near-duplicate `_safe_round`, which passes every visible
test, so the hidden checks print `"behavior_changed": true`. Catching it is the job of the judge
and the probes, which need the LLM; with a key, the toy repo's outcome is 13/13 and hidden
behavior is unchanged (Results summary below).

Methods: `cleansweep`, `guard_tests_only`, `tools_only`, `one_shot_llm`, `one_shot_retry`,
`no_ranker`, `no_batching`. Every package has a stub with the same interface;
`CLEANSWEEP_STUBS=analysis,guard` (or `all`) swaps packages for their stubs.

## How it works

The pipeline, packages, interfaces and every setting are described in [docs/architecture.md](docs/architecture.md).

### Judge

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

The judge model is `VOYAGER_MODEL` in `.env` (we use `qwen36-35b-a3b`).

Two policies run after the judge (both on by default since v1.0): `keep_public_api: auto` keeps
dead code on public names in package modules in the suggest lane, and `framework_callbacks: on`
does the same for methods a framework calls by name (Textual, Django, Flask/FastAPI,
Click/Typer, pytest).

### Guard

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

Probes run in one of two modes (`core.guard.probe_mode`).
- `direct`: the harness runs as a script with the project folder on the path.
- `runner`: the probes go into a generated test file next to the project's own tests, and the project's test command runs it. On SWE-bench that is the instance's own command and setup, for example Django's `runtests.py` with its settings; on AIDev it is pytest with the `conftest.py` files.

The default, `auto`, uses runner mode in containers (SWE-bench, AIDev) and direct mode for local folders. Without the test setup, Django modules can't even be imported.

Settings are under `core.guard` in `configs/base.yaml` (`diff_tests`, `max_targets` and the
`probe_*` keys). The `guard_tests_only` method turns the probes off.

## Demo

`demo/shop_app` is a small bookstore inventory app with 11 tests and 7 planted problems.
`demo/feature.patch` is the kind of change a coding agent makes: a new `lowstock` command
that also leaves a helper behind. The timed script is in `demo/run_demo.md`.

```bash
bash demo/prepare_demo.sh --with-feature   # builds .cleansweep/demo/shop_app as a git repo
streamlit run app/dashboard/dashboard.py             # then open the "Live sweep" page
```

On **Live sweep**, pick a target (toy repo, prepared demo, `demo/shop_app` or any path), a
method and a judge mode, and press **Run**. The page shows each stage as it finishes, the
Reviewer's plan, one card per Guard check (including bisection splits), the diffs, the
hidden-check verdict, the score against the answer key, and the run log. Every run is saved
under `results/raw/live/<run_id>/`, and **Replay** plays a saved run back at 1–50x without
calling the LLM or running tests. Three demo recordings ship in `demo/replay/`, so Replay works
offline on a fresh clone; `20261030_demo_feature_advisory_v1` is the advisory run with the v1.0
defaults (outcome 7/7, hidden behavior unchanged). To record a run without the browser:

```bash
python -m cleansweep.live --target .cleansweep/demo/shop_app --judge-mode advisory
```

## Studio

CleanSweep Studio is the v2 web UI: it starts runs, follows them live, replays recordings and
shows the results. It needs node 20 or later once, to build the frontend.

```bash
cleansweep studio                  # builds app/studio/frontend if needed, opens http://127.0.0.1:8765
cleansweep studio --port 8800 --runs ../studio-runs --no-browser
```

Without npm, build the frontend by hand: `cd app/studio/frontend && npm ci && npm run build`.
Runs started from Studio go to `results/raw/studio/` (or `--runs`); Studio reads only that folder,
`results/` and `demo/replay/`, never serves `.env` or other hidden or secret files, and masks
anything that looks like a key. Replay works offline on the agent-team recordings in `demo/replay/`:
`20261101_toy_clean_offline` (the toy repo, recorded with `--no-llm`),
`20261102_demo_feature_agentic` (the demo app with the feature patch, real model),
`20261101_manager_conflict_step_back` (the Manager goes back from FINAL VERIFY to EXECUTE and
undoes only the package that broke a test) and `20261101_skill_seekers_case_study` (the
Skill_Seekers case study in safe mode; two product names in that project's code are replaced by
"Assistant" and "Vendor"). `scripts/tools/make_recording.py` copies a run folder into a
recording with relative paths and refuses one with a secret left in it.

Screens: **Runs** (every recording), **Launch** (clean, sweep or watch a project), **Live run** and
**Replay** (phase timeline with step-backs and the Manager's decisions, the agent graph, the
message board, the item board, work packages with diffs, tests, probes and checks, metrics and
budget gauges; Replay adds play/pause, step, 1–50x, a scrubber and "next decision"), **Compare**,
**Case studies** (health before and after, diffs, report, review sheet with the
"LLM-reviewer acceptance (independent model, blinded)" decisions), **Watch** (commit stream, slop
over time, decisions with reasons) and **Results**, plus the dashboard's pages (Live sweep and
Replay of v1 runs, Scheduler, Baselines, Data, Guard). The user guide describes each screen.

## Reproduce

```bash
bash scripts/reproduce_tables.sh
```

rebuilds the aggregate tables and figures (`results/summary/v1/`, `results/figures/v1/`) offline
from the committed per-run CSVs; on a clean checkout `git status results/` shows no change afterwards.
[docs/experiments.md](docs/experiments.md) has, for every experiment, the command, the commit it
ran at, its inputs and outputs, runtime and models, how to download the data (SWE-bench
Verified, PatchDiff, AIDev), and the Docker and disk needs (about 65 GB for all images and
data).

## Results summary

Means per target with 95% bootstrap CIs; hidden changed = the hidden checks (tests the Guard
never sees) give a different result after the cleanup. Full tables in
[docs/results.md](docs/results.md).

**SWE-bench Tier 2: 57 agent patches, the headline.** CleanSweep removes about as much as an
unchecked one-shot LLM cleanup and breaks nothing; stronger one-shot variants close part of the
gap (`oneshot_series.md`; McNemar and Wilcoxon against gatekeeper). `one_shot_compile` is a
re-score of the `one_shot_llm` runs (`scripts/experiments/v1/exp_collect.py`), not a `--method`:

| method | lines removed | hidden changed | McNemar p | Wilcoxon p |
|---|---|---|---|---|
| cleansweep, gatekeeper | 37.4 [25.7, 53.5] | **0/57** | | |
| `one_shot_llm` | 30.1 [21.0, 41.0] | **9/57** | 0.0039 | 0.70 |
| `one_shot_compile` (discard a diff that doesn't compile) | 27.8 [19.0, 38.9] | 2/57 | 0.5 | 0.087 |
| `one_shot_retry` (one retry on the compile errors) | 30.1 [21.0, 41.0] | 5/57 | 0.063 | 0.73 |

On SWE-bench, CleanSweep's edits were all leftover files the agents created, so the evidence for
code-level edits comes from the rest:

- **Answer keys** (toy repo, demo app): the probes catch the near-duplicate trap that every test
  passes, and the judge keeps it out in gatekeeper mode; outcome 13/13 and 7/7, hidden behavior
  unchanged, where `guard_tests_only` and `tools_only` change it.
- **Guard strength:** tests then runner-mode probes catch 36 of 39 mutants in agent-written
  functions on Tier 1 and 135 of 189 on the other 47 Tier 2 patches, with 0 false alarms on 56
  identical copies. As a
  filter on the one-shot cleanup, the Guard blocks all 12 runs that changed hidden behavior.
- **AIDev, 20 repositories** (agent-written code only; hidden tests by a second model). As run,
  CleanSweep changed hidden behavior on 3 of 19 repositories, every time by deleting a function
  nothing in the project calls. The v1.0 policies, re-scored on the same runs
  (`aidev_final_policy.md`):

| method | lines removed as run | hidden as run | lines removed, v1.0 policies | hidden, v1.0 policies |
|---|---|---|---|---|
| cleansweep, gatekeeper | 64.8 [12.1, 133.4] | 3/19 | 12.2 [1.9, 30.0] | **0/19** |
| cleansweep, advisory | 121.7 [18.9, 292.9] | 3/19 | 31.3 [7.0, 63.3] | **0/19** |
| `guard_tests_only` | 128.9 [20.1, 303.4] | 4/19 | 33.5 [8.7, 65.2] | 1/19 |
| `one_shot_llm` | 347.6 [170.7, 551.8] | 2/19 | | |

- **The judge and the Guard catch different things**, which is why gatekeeper is the default.
  On pytorch_connectomics the duplicate finder matched `divide_rows` with `divide_columns`: the
  judge vetoed the merge, advisory's probes rolled it back, and `guard_tests_only` kept it and
  failed a hidden test. On shotgun (a Textual app) the judge vetoed 49 of 53 framework callbacks
  that nothing in the project calls; without the judge the Guard deleted 35 with every test
  passing, and a headless UI check shows 17 screens and widgets changed (0 with the framework
  rule; `framework_callbacks.csv`, `shotgun_ui.csv`).
- **Dependency removals:** re-checked by uninstalling, 14 of the 18 applied ones hold (11 of
  them because another installed package still needs the package); 4 break tests. The Guard
  now runs this check (`aidev_dependency_check.csv`).
- **Scheduler:** sweeping daily cuts slop debt by 87% [79, 94] against never sweeping, at 1.8×
  the test runs of sweeping after every agent PR (61% [44, 75]).
- **Self-sweep:** CleanSweep on its own code found 2 of its own bugs (format edits ignored the
  project's line length; `reviewer.exclude` missed the over-engineering review); we applied none
  of its edits (`self_sweep.csv`).
- **Negative results:** the detectors find few of the removals human reviewers ask for (recall
  0.075), and a ranker trained on those requests is barely better than the base rate (AUC 0.607).

## Known limitations

- **Unused is not unneeded.** The Guard can't check the deletion of a function nothing in the
  project calls: there is nothing to run. `keep_public_api: auto` keeps public names in package
  modules in the suggest lane, and the framework rule keeps framework callbacks there; anything
  else relies on the judge.
- **The framework rule knows five frameworks** (Textual, Django, Flask/FastAPI, Click/Typer,
  pytest; `analysis/frameworks.py`). Callbacks of other frameworks look like dead code.
- **Probes check only what the model thinks to call.** A target that needs files, the network
  or the clock gets no probe cases; direct-mode probes can't set up a framework (runner mode,
  the default in containers, can).
- **Dependency removals are verified only where packages can be uninstalled** (AIDev
  containers). Local and SWE-bench workspaces mark them "checked statically only".
- **Format edits follow ruff's settings** (`ruff.toml`, `[tool.ruff]`, or ruff's defaults),
  not black's or another formatter's.
- **Rewrites only handle uses in the same file**; other duplicates go to the suggest lane.
- **Judge decisions are model output.** They were consistent across runs and models on the
  answer keys, but that isn't guaranteed. The run seed is recorded, not sent to the judge.
- **Scale.** Duplicate finding is pairwise (O(n²)), fine for agent-scoped code but slow on a
  whole large repository. A timed-out model request (600 s) is not retried.
- **Measurement.** SWE-bench images run under amd64 emulation on arm64; hidden checks on AIDev
  are second-model tests of public functions, so they don't see UI callbacks or uninstalled
  packages; the scheduler replay uses static detectors and estimated test runs.
- **The ranker** predicts "a reviewer asked to remove this", not "safe to remove", so it is off
  by default.

## Repository layout

Every folder and what it is for: [docs/repo_layout.md](docs/repo_layout.md). All documents:
[docs/index.md](docs/index.md).

```
src/cleansweep/
  core/        contracts (models.py), config, JSON io, stub switch
  llm/         Voyager client with disk cache, FakeLLM for tests
  sandbox/     git-backed workspaces: local folders, SWE-bench and AIDev Docker containers
  guard/       applies edits, verifies them (tests, AST, differential probes), rolls back failures
  workflow/    run_sweep: open -> analyze -> plan -> rank -> batch -> guard -> report
  agents/      v2 agent team behind `cleansweep clean` and method=agentic
  analysis/    code graph, duplicate finder, features
  reviewer/    detectors, duplicate/wrapper rewrites, LLM judge, over-engineering review, repair, planner
  ranking/     safe-to-remove scores (category priors; a classifier trained on AIDev labels)
  scheduler/   batching with bisection, sweep policies, history replay
  eval/        baselines, hidden checks, metrics, mutation testing, statistics
  data/        SWE-bench Verified, PatchDiff and AIDev loaders, tier splits
  mining/      review-comment mining: removal requests, taxonomy, rules
app/dashboard/ Streamlit dashboard, Live sweep and Scheduler pages, step-by-step live runner
app/studio/    CleanSweep Studio: FastAPI server (`cleansweep studio`) and React frontend
demo/          bookstore demo app, answer key, hidden tests, feature patch, demo script, Replay recordings
scripts/       data/, experiments/v1 and v2/, report/, tools/, reproduce_tables.sh
results/       summary/v1 and figures/v1 (v1 tables and figures; v2 in Phase 4), data_summary/
data/splits/   committed tier and repository splits
docs/          index, user guide, architecture, agentic design, experiments, results, layout
configs/       base.yaml (core and agents), data.yaml, exp.yaml, reviewer.yaml
tests/         mirrors src/, app/ and scripts/, plus fixtures/ (toy repo, answer key, hidden tests,
               sample report, small results set)
```

## Team

Roles follow the proposal, except that the Reviewer moved from the Software architect to the
Project manager. Ritik Agarwal (Project manager, UI lead) built a cross-area prototype on the
first day, then the Reviewer, the toy repository and demo app, the dashboard and the report
assets. Because no other member had joined the repository before the milestones, the Project
manager also built the critical path in the other areas, as recorded in our decision log: the
differential probes and their runner mode, the SWE-bench and PatchDiff loaders and Docker
workspaces, the SWE-bench evaluation and statistics, the AIDev selection, mining, labels,
replay and ranker, and the reliability work on the LLM client. The owners of record are
Maninderjit Singh Bhullar (Software architect: LLM client, sandboxes, Guard, workflow), Badri
Sri Vaishnavi Yeluri (Data architect: loaders, AIDev, code graph, comment mining) and Simran
Sharma (Experiment architect: ranker, Scheduler replay, baselines, evaluation).
