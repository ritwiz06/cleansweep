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
```

`results/raw/` is git-ignored; Studio's **Saved reports** screen (`cleansweep studio`, below)
shows every report saved under it. Without a key, the toy sweep applies the planted
near-duplicate `_safe_round`, which passes every visible test, so the hidden checks print
`"behavior_changed": true`. Catching it is the job of the judge and the probes, which need the
LLM; with a key, the toy repo's outcome is 13/13 and hidden behavior is unchanged (Results
summary below).

Methods: `cleansweep`, `guard_tests_only`, `tools_only`, `one_shot_llm`, `one_shot_retry`,
`no_ranker`, `no_batching`. Every package has a stub with the same interface;
`CLEANSWEEP_STUBS=analysis,guard` (or `all`) swaps packages for their stubs.

### Clean your own project (v2)

```bash
cleansweep clean path/to/project --dry-run   # plan only: writes blueprint.md, changes nothing
cleansweep clean path/to/project             # safe mode: deterministic edits, each one verified
cleansweep clean path/to/project --mode thorough --budget llm=150,minutes=60,tests=80
cleansweep clean tests/fixtures/toy_repo --no-llm   # try it offline on the toy repo
```

The original folder is never changed. `clean` copies the project into
`<project>-cleanup-<time>/` next to it (or `--out`), and the agent team cleans the copy one work
package at a time, keeping a package only if the tests and the probes still pass. It ends with a
git branch in that copy (one commit per package), `CLEANUP_REPORT.md`, `blueprint.md`, the
patches and a PR description; apply the branch yourself after reading the report. The exit code
is 0 when the result is "everything runs" or "nothing applied".

Settings that a project always wants go in a `.cleansweep.yaml` at its root (or any file passed
with `--config`); a command-line option overrides the file:

```yaml
mode: safe                                # or thorough
budget: {llm: 150, minutes: 60, tests: 80}
exclude: [tests/fixtures, docs/examples]  # folders the cleanup leaves alone
test_args: "-m 'not slow'"                # extra pytest arguments
install: auto                             # off: run the tests with CleanSweep's interpreter
model: my-model                           # default: VOYAGER_MODEL
```

The [user guide](docs/user_guide.md) explains the output and every option.

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
cleansweep studio                           # then open Launch
```

On **Launch**, choose **Sweep (v1 pipeline)**, a target (toy repo, demo app, prepared demo or
any folder), a method and a judge mode, and press **Start**. The live run shows each stage as
it finishes, the Reviewer's plan, one card per Guard check (including bisection splits), the
diffs, the hidden-check verdict, the score against the answer key, and the run log. Studio
saves its runs under `results/raw/studio/`, and **Replay** on **Live sweep and replay** plays a
saved run back at 1–50x without calling the LLM or running tests. Three v1 demo recordings ship
in `demo/replay/`, so Replay works offline on a fresh clone; `20261030_demo_feature_advisory_v1` is the advisory run with the v1.0
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
over time, decisions with reasons) and **Results**, plus the dashboard's pages (saved reports,
Live sweep and Replay of v1 runs, Scheduler, Baselines, Data, Guard). The user guide describes each screen.

## Reproduce

```bash
bash scripts/reproduce_tables.sh
```

rebuilds the aggregate tables and figures (`results/summary/v1/` and `v2/`, `results/figures/v1/`)
offline from the committed per-run CSVs; on a clean checkout `git status results/` shows no change
afterwards.
[docs/experiments.md](docs/experiments.md) has, for every experiment, the command, the commit it
ran at, its inputs and outputs, runtime and models, how to download the data (SWE-bench
Verified, PatchDiff, AIDev), and the Docker and disk needs (about 65 GB for all images and
data).

## v2 results: the agent team

`cleansweep clean` and `method=agentic` (the agent team, safe mode, `qwen36-35b-a3b`) against
v1's sweep (`method=cleansweep`, gatekeeper). Hidden changed = the hidden checks (tests no agent
sees) give a different result after the cleanup. Code lines removed counts lines removed from
non-test Python files in the final diff, measured the same way for both versions (v1 from its
archived reports). Means per target with 95% bootstrap CIs; full tables, per-target rows and
how each was run in [docs/results.md](docs/results.md#v2-the-agent-team).

| target set | runs | team: everything runs / nothing applied / not verified | team: code lines removed | team: hidden changed | v1: code lines removed | v1: hidden changed | LLM requests, team vs v1 | minutes, team vs v1 (median) |
|---|---|---|---|---|---|---|---|---|
| answer keys (toy, demo ×3) | 6 | 6 / 0 / 0 (60/60 planted items) | 57.0 [51.7, 62.3] | 0/6 | 57.0 [51.7, 62.3] | 0/6 | 41.5 vs 5.5 | 1.7 vs 4.8 |
| SWE-bench Tier 1 | 10 | 7 / 3 / 0 | 37.5 [9.2, 73.1] | 0/10 | 37.5 [9.2, 73.1] | 0/10 | 11.8 vs 0.8 | 1.1 vs 1.5 |
| SWE-bench Tier 2 subset | 20 | 16 / 4 / 0 | 15.2 [8.2, 22.8] | 0/20 | 15.2 [8.2, 22.8] | 0/20 | 9.1 vs 1.4 | 1.1 vs 2.4 |
| AIDev | 6 | 4 / 2 / 0 | 46.7 [1.3, 134.5] | 0/6 | 256.2 [116.8, 400.7] | 3/6 | 73.0 vs 17.2 | 11.1 vs 78.5 |

- On the answer keys and SWE-bench the two versions remove exactly the same code (342, 375 and
  303 lines in total). On SWE-bench that is the scratch files the coding agents left at the
  repository root (`reproduce_error.py`, a whole `test_app/` Django project); we read every diff (LLM-judged: by the coding assistant that ran
  the evaluation, not a person).
- On AIDev, v1 as it ran removed more and changed hidden behavior on 3 of the 6 repositories,
  each time by deleting a function nothing in the project calls that the hidden tests use as
  public API (paired: McNemar p = 0.25, Wilcoxon p = 0.063, n = 6). The team kept those functions
  because its Auditor runs v1's detectors with the v1.0 public-API rule, which v1's recorded runs
  predate; re-scored with that rule, v1 changes 0 of 19 (v1 results below). The six were chosen
  from v1's results (its three hidden changes, the near-duplicate and framework-callback cases,
  one clean repository), so they lean toward v1's hardest cases.
- Reading every diff of the team's (LLM-judged, as above) found one wrong edit the hidden checks
  cannot see: on pytorch_connectomics it removed a `pdb.set_trace()` under `if self.debug_on_nan:`,
  an opt-in debugger. A debugger call behind a condition is only a suggestion since #124, after
  these runs.
- The team spends more LLM requests (41.5 against 5.5 on the answer keys) and fewer minutes; the
  ablations below show where the requests go.
- The first SWE-bench runs saw no tests (the workspace never stored test statuses) and are not
  reported; the reruns above have baselines of 5 to 428 passing tests (#118).

**Slop-injection benchmark** (`injection_summary.csv`, seed 1): seven kinds of slop and two traps
(a near-duplicate that rounds differently, a framework callback) planted in the toy repository and
9 AIDev repositories; each method cleans the whole project. Planted items removed, of 10 per kind:

| | leftover file | dead code | exact duplicate | unused import | debug print | commented-out code | unused dependency | all (of 70) | traps removed (of 20) | hidden changed |
|---|---|---|---|---|---|---|---|---|---|---|
| team | 9 | 9 | 0 | 7 | 9 | 9 | 7 | 50 (0.71) | 0 | 0/8 |
| v1 | 10 | 10 | 0 | 8 | 0 | 0 | 10 | 38 (0.54) | 0 | 0/8 |
| one-shot LLM (toy repo only) | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 6 (0.09) | 2 | 1/8 |

The team finds the debug prints and commented-out code v1 has no detector for. Seven of its 20
misses are one project where the run stopped on a template file named `*.py` (an edit that
raises is skipped since #125, after these runs); neither version's detectors flagged a planted
duplicate. The benchmark has flaws we report rather than hide: on openwebui-extensions it
planted into that template file, so its hidden test cannot run, and on imgviz the hidden test
failed before every cleanup (hidden changed counts the other 8); the one-shot baseline, as in
v1, sees only lines agent pull requests wrote, an empty scope in the injected AIDev clones, so
its row is the toy repository alone.

**Ablations** (`ablations.md`): one part of the team switched off, on the answer keys (6 runs
each) and the injected set (one run on each of the 10 projects).

| variant | answer keys: planted found (of 60) | hidden changed (of 6) | LLM requests | injected: planted removed (of 70) | traps removed (of 20) | hidden changed (of 8) | LLM requests |
|---|---|---|---|---|---|---|---|
| team (LLM Manager) | 60 | 0 | 41.5 | 50 | 0 | 0 | 92.1 |
| rule-based Manager | 60 | 0 | 37.2 | 50 | 0 | 0 | 87.0 |
| no research squad | 60 | 0 | 11.7 | 53 | 0 | 0 | 9.8 |
| broadcast messages | 60 | 0 | 43.7 | 50 | 0 | 0 | 90.8 |
| artifacts inlined | 60 | 0 | 41.7 | 49 | 0 | 0 | 90.8 |
| no lessons | 57 | 0 | 43.2 | 47 | 0 | 0 | 93.3 |
| no coverage guidance | 60 | 0 | 42.8 | 50 | 0 | 0 | 90.7 |
| single agent | 54 | 4 | 36.2 | 35 | 5 | 4 | 83.6 |

- **Checking apart from editing is what keeps the cleanup safe.** The single agent (one LLM with
  every tool, keeping or reverting its own edits) changed hidden behavior in 4 of 6 answer-key
  runs and on 4 of the 8 injected projects, by merging the near-duplicate or deleting the
  framework callback, and called 3 of those 4 injected projects "everything runs".
- **The research squad costs requests without adding recall or safety here.** Without it the
  team found the same on the answer keys at about a quarter of the requests, and 3 more on the
  injected set at about a tenth: 2 on CORAL, where the full team's 150 requests ran out before
  the Investigator decided, and the planted `tabulate` on imgviz, which the Investigator wrongly
  kept: its reference search found a local function named `tabulate` in `generate_readme.py`,
  and it took that for an import. Whether investigation pays off on real projects is open: no
  ablation ran there.
- The rule-based Manager, broadcast messages, inlined artifacts and no coverage guidance match
  the team within one item. Without lessons the team missed 3 on the answer keys (two of those runs
  ran out of test runs) and 3 on the injected set, in runs where no package rolled back, so no
  lesson was missing (one run each).

**Probe strength** (`probe_strength.csv`): v1's mutants and PatchDiff patches, checked by the
tests and then the coverage-guided probes. On the 163 mutants and patches both versions checked,
the two catch the same ones except one toy mutant that v1's probes caught
(`probe_strength_vs_v1.csv`).

| target set | mutants caught | caught by the tests | only by the probes | PatchDiff recall |
|---|---|---|---|---|
| toy repo | 19/20 | 15 | 4 | |
| demo app | 18/20 | 15 | 3 | |
| SWE-bench Tier 1 | 36/39 | 30 | 6 | 0/3 |
| SWE-bench Tier 2 subset | 53/81 | 52 | 1 | 3/18 (all by the probes) |

**Manager scenarios** (`manager_scenarios.csv`, 3 runs each): the LLM-guided Manager against the
same rules without the LLM.

| scenario | right answer | LLM Manager | rules |
|---|---|---|---|
| conflict | go back to EXECUTE and undo only the package that broke a test | 3/3 | 3/3 |
| budget | stop at 85% of the test-run cap and deliver the verified packages | 3/3 | 0/3 (went on) |
| no baseline | change nothing and say why | 3/3 | 3/3 |
| rollbacks | go back to INVESTIGATE or replan after half the packages roll back | 0/3 (went on) | 0/3 (went on) |

Every run of both ended no worse than its baseline.

**Case studies** (`results/raw/case_studies/`, local; safe mode unless noted). Each review
sheet was scored by an independent model shown only the code and the change, never the agents'
verdict: "LLM-reviewer acceptance (independent model, blinded)", 3 votes per row
(`llm_review_acceptance.csv`). It is an LLM's judgment, not a human review.

| project | tests before → after | lines removed | result | LLM-reviewer acceptance: applied | suggestions |
|---|---|---|---|---|---|
| this repository | 335 → 335 | 0 (its one package rolled back) | everything runs | | 9 accept, 16 reject, 3 unsure |
| slop-guard | 182 | 0 | nothing applied (thorough: everything runs, its one package rolled back) | | 12 / 18 / 5 |
| Skill_Seekers | 4,442 → 4,442 | 11 | everything runs | 6 / 0 / 1 | 14 / 21 / 5 |
| shotgun | 2,254 → 2,256 | 298 | everything runs | 6 / 0 / 2 | 2 / 37 / 1 |
| Telegram-Snowball-Sampling | 27 → 27 | 6 | everything runs | 0 / 1 / 0 | 21 / 10 / 2 |

"Everything runs" means the tests ran and nothing got worse, also when every package rolled
back (this repository, slop-guard in thorough mode).

**Detection** (`detection.csv`): of 163 removals human reviewers asked for in 116 AIDev pull
requests, v1's static detectors flag 19 (recall 0.117) and the team's Auditor (v1's detectors
plus the line-level ones) 24 (0.147).

**Watch** (`watch_replay.csv`, 20 AIDev histories, static detectors): the watch rule leaves a
mean slop debt of 41 open items summed over the commits, against 693 for a daily sweep and
9,863 for never sweeping, at 68.7 estimated test runs against 27.7; held to the adaptive
policy's test budget it does worse than every policy but never sweeping (8,841).

## v1 results summary

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
app/studio/    CleanSweep Studio: FastAPI server (`cleansweep studio`) and React frontend
demo/          bookstore demo app, answer key, hidden tests, feature patch, demo script, Replay recordings
scripts/       data/, experiments/v1 and v2/, report/, tools/, reproduce_tables.sh
results/       summary/v1, summary/v2 and figures/v1 (tables and figures), data_summary/
data/splits/   committed tier and repository splits
docs/          index, user guide, architecture, agentic design, experiments, results, layout
configs/       base.yaml (core and agents), data.yaml, exp.yaml, reviewer.yaml
tests/         mirrors src/, app/ and scripts/, plus fixtures/ (toy repo, answer key, hidden tests,
               sample report, small results set)
```

## Team

Roles follow the proposal, except that the Reviewer moved from the Software architect to the
Project manager. Ritik Agarwal (Project manager, UI lead) built a cross-area prototype on the
first day, then the Reviewer, the toy repository and demo app, the v1 dashboard and the report
assets. Because no other member had joined the repository before the milestones, the Project
manager also built the critical path in the other areas, as recorded in our decision log: the
differential probes and their runner mode, the SWE-bench and PatchDiff loaders and Docker
workspaces, the SWE-bench evaluation and statistics, the AIDev selection, mining, labels,
replay and ranker, and the reliability work on the LLM client. The owners of record are
Maninderjit Singh Bhullar (Software architect: LLM client, sandboxes, Guard, workflow), Badri
Sri Vaishnavi Yeluri (Data architect: loaders, AIDev, code graph, comment mining) and Simran
Sharma (Experiment architect: ranker, Scheduler replay, baselines, evaluation).
