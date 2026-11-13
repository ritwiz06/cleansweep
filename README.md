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
policies leave CleanSweep with 0 of 19 hidden changes.

v2's agent team, on a benchmark of slop planted in 10 projects (3 seeds), removed 81% of the
planted items [77, 84], removed no trap and changed hidden behavior in none of its 30 runs, yet a
blinded audit found 18 wrong edits among its 804 kept code edits (12 confirmed by targeted tests,
the rest by reading, LLM-judged) that no test, probe or hidden check caught, 14 of them code a
framework or grader calls by name. A single agent with the same tools removed fewer planted items
(114 against 170, p < 0.0001), changed hidden behavior in 16 of 30 runs (p < 0.0001) and kept 63
wrong edits of 489 (50 confirmed): a single agent that checks its own edits is not safe.
On five real projects, one run each, the audit flagged none of the team's 14 kept code edits,
against 4 wrong of 20 without its research squad (Fisher p = 0.13) and 17 of 65 for the single
agent (p = 0.03), which suggests, but doesn't establish, that investigating each candidate pays
off on real code. Against v1 the team is about as safe on the confirmed tier (12 of 804 wrong
against 13 of 610) and lower across all tiers (18 against 48, 35 of v1's by reading); on AIDev it
removed about a fifth of v1's code lines, so part of its safety there is caution. The auditor never sees the method, so
its wrong counts are lower bounds not biased by who made the edit. Re-scored with the framework
rule, which was extended after these failures, the team's 18 become 9; that estimate is in-sample
and so optimistic. Details below and in [docs/results.md](docs/results.md).

v3 (Phase 3) tested the team as pre-registered. Every method had one 120-minute cap and one
400-request budget, and the team was compared with the outside agent Aider. The tests ran on 10
new projects with planted slop and on 15 real projects whose held-out tests no method sees.
- **H1, not supported.** On the real projects, the team's kept edits were wrong far less often
  than Aider's: 4 of 191 confirmed by tests, against 4 of 13; 13 of 191 against 5 of 13
  counting LLM-judged readings. But Aider kept almost nothing and changed no held-out test,
  while the team changed held-out behavior on 4 of 10 paired projects.
- **H2, not supported.** The resolver did not lower wrong edits.
- **H3, supported by a tie.** Batching used 41% of the team's requests with the same number of
  wrong edits.
- **H4, supported, at the threshold.** 27 of 30 repositories ran end to end.
- **No human checked the labels.** Three LLM judges agree with the recorded labels at
  κ = 0.455 (wrong vs not wrong), and are right on 11 of 18 confirmed verdicts (each confirmed
  by a targeted test or a rule).

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
cleansweep clean path/to/their/project --untrusted   # their code runs only in a Docker container
```

Or run CleanSweep itself in a container (`docker build -t cleansweep -f docker/Dockerfile .`
once; the key comes from your environment, never from the image):

```bash
docker run --rm -e VOYAGER_API_KEY -e VOYAGER_BASE_URL -e VOYAGER_MODEL -v "$PWD:/project:ro" -v "$PWD-cleanup:/out" cleansweep clean /project --out /out
```

The original folder is never changed. `--sandbox auto` (the default) runs the project's
code on your machine only for a git repository you own, and in a network-less Docker
container otherwise (`--sandbox docker|none` to choose). `clean` copies the project into
`<project>-cleanup-<time>/` next to it (or `--out`), and the agent team cleans the copy one work
package at a time, keeping a package only if the tests and the probes still pass. It ends with a
git branch in that copy (one commit per package), `CLEANUP_REPORT.md`, `blueprint.md`, the
patches and a PR description; apply the branch yourself after reading the report. The exit code
is 0 when the result is "everything runs" or "nothing applied"; the other results are "not
verified by tests" (no usable tests: only probe-covered edits applied), "not verified" and
"stopped: <reason>, nothing applied" ([user guide](docs/user_guide.md#the-result)). An
interrupted run continues with `cleansweep clean --resume <its output folder>`.

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

## v3 results: the evaluation (frozen 2026-11-13 12:00)

Every method on every set had one cap (120 minutes) and one budget (400 LLM requests); a run that
hits either counts as timed out, with nothing removed. Hypotheses, metrics and thresholds are in
[docs/preregistration_v3.md](docs/preregistration_v3.md), with its nine dated deviations; the
tables are in `results/summary/v3/` and every number in
[docs/results.md](docs/results.md#v3-the-evaluation-phase-3-frozen-2026-11-13-1200).

| | Hypothesis | Result |
|---|---|---|
| H1 | On real projects, the team makes fewer wrong edits than Aider in both tiers, and fewer held-out failures | not supported: fewer wrong edits (4/191 vs 4/13 confirmed, p=0.0006; 13/191 vs 5/13 all tiers, p=0.0025), but held-out changes on 4 vs 0 of 10 projects |
| H2 | The resolver lowers the team's wrong edits on the planted-slop set | not supported: 3 vs 3 over 9 repositories |
| H3 | Batching keeps the team's safety at no more than 60% of its requests | supported, by a tie: 41% of the requests, 16 vs 16 wrong edits |
| H4 | At least 90% of 30 repositories run end to end | supported: 27 of 30 (0.900) |

On the planted-slop set (out of sample) the team removed 72% of the planted items and no trap.
The single agent removed 3 traps and Aider 4, and each changed the hidden test in 3
repositories. Wrong counts in "all tiers" include LLM-judged readings, and no human checked
them. A panel of three LLM judges agrees with the recorded labels at κ = 0.455 (wrong vs not
wrong), and is right on 11 of 18 confirmed verdicts, each confirmed by a targeted test or a rule
(`judge_panel.md`).

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
  these runs; rerun with that fix (`results/raw/v2_eval/aidev_after124/`), the team suggested
  all 153 candidates on pytorch_connectomics, applied nothing and left the hidden checks
  unchanged.
- The team spends more LLM requests (41.5 against 5.5 on the answer keys) and fewer minutes; the
  ablations below show where the requests go.
- The first SWE-bench runs saw no tests (the workspace never stored test statuses) and are not
  reported; the reruns above have baselines of 5 to 428 passing tests (#118).

**Slop-injection benchmark** (`injection_seeds.md`, `injection_paired.md`,
`injection_summary.csv`): seven kinds of slop and two traps (a near-duplicate that rounds
differently, a framework callback) planted in the toy repository and 9 AIDev repositories. Each
plant is checked to be a right answer, and each hidden test passes on the injected project before
any cleanup; each method then cleans the whole project. The team, the no research squad and the
single agent ran three seeds (30 runs each), v1 and the one-shot LLM two (20 runs). Planted items
removed per kind:

| | leftover file | dead code | exact duplicate | unused import | debug print | commented-out code | unused dependency | all planted | traps removed | hidden changed |
|---|---|---|---|---|---|---|---|---|---|---|
| team | 30/30 | 29/30 | 0/30 | 26/30 | 30/30 | 30/30 | 25/30 | 170/210 (0.81) | 0/60 | 0/30 |
| no research squad | 30/30 | 28/30 | 0/30 | 29/30 | 30/30 | 30/30 | 29/30 | 176/210 (0.84) | 2/60 | 2/30 |
| single agent | 30/30 | 26/30 | 0/30 | 27/30 | 9/30 | 6/30 | 16/30 | 114/210 (0.54) | 16/60 | 16/30 |
| v1 | 20/20 | 19/20 | 0/20 | 19/20 | 0/20 | 0/20 | 20/20 | 78/140 (0.56) | 1/40 | 1/20 |
| one-shot LLM | 19/20 | 19/20 | 19/20 | 14/20 | 18/20 | 18/20 | 0/20 | 107/140 (0.76) | 36/40 | 19/20 |

- Paired by project and seed (`injection_paired.md`):
  - **Team vs the single agent:** 170 against 114 planted items removed (Wilcoxon p < 0.0001); 0 against 16 hidden changes (McNemar p < 0.0001).
  - **Team vs the no research squad:** 170 against 176 (p = 0.063); 0 against 2 hidden changes (p = 0.5).
  - The team's share per seed is 0.81, 0.80 and 0.81 (`injection_seeds.md`, with 95% CIs).
- Every trap the single agent, the no research squad and v1 removed is the framework callback (`visit_Name`, which `ast.NodeVisitor` calls by name). None of them merged the near-duplicate.
- The one-shot LLM removes most of the slop, including the exact duplicates that no detector-based method touches. It also removes 36 of the 40 traps and changes hidden behavior in 19 of 20 runs.
- **Team against v1, on the seeds both ran** (1 and 2, `injection_summary_seeds12.csv`): 113 against 78 of 140 planted items. The whole gain is in the two kinds the line-level detectors find, debug prints (20 against 0 of 20) and commented-out code (20 against 0), for which v1 has no detector; v1 removed a few more unused dependencies (20 against 17) and unused imports (19 against 17).
- Four projects are left out, with the reasons in `EXCLUDED` (`exp_inject.py`):
  - imgviz: its hidden test failed before any cleanup;
  - openwebui-extensions: its hidden test failed on every injected draw;
  - skillport and chatlas: too few modules to plant in.
- Runs spoiled by a laptop sleep were rerun and replace them. The spoiled ones are kept apart (`results/raw/inject_superseded/`) and are not reported.

**Ablations** (`ablations.md`): one part of the team switched off. On the answer keys, 6 runs
each. On the injected set, the same project-seed runs as above: 30 for the team, the no research
squad and the single agent; 20 for the other variants, which ran seeds 1 and 2.

| variant | answer keys: planted found (of 60) | hidden changed (of 6) | LLM requests | injected: planted removed | traps removed | hidden changed | LLM requests |
|---|---|---|---|---|---|---|---|
| team (LLM Manager) | 60 | 0 | 41.5 | 170/210 | 0/60 | 0/30 | 92.3 |
| rule-based Manager | 60 | 0 | 37.2 | 113/140 | 0/40 | 0/20 | 87.5 |
| no research squad | 60 | 0 | 11.7 | 176/210 | 2/60 | 2/30 | 9.7 |
| broadcast messages | 60 | 0 | 43.7 | 113/140 | 0/40 | 0/20 | 91.2 |
| artifacts inlined | 60 | 0 | 41.7 | 112/140 | 0/40 | 0/20 | 91.2 |
| no lessons | 57 | 0 | 43.2 | 111/140 | 0/40 | 0/20 | 93.7 |
| no coverage guidance | 60 | 0 | 42.8 | 113/140 | 0/40 | 0/20 | 91.0 |
| single agent | 54 | 4 | 36.2 | 114/210 | 16/60 | 16/30 | 84.9 |

- **One agent that checks its own edits is not safe.** The single agent is one LLM with every tool, keeping or reverting its own edits. It changed hidden behavior in 4 of 6 answer-key runs (merging the near-duplicate) and in 16 of 30 injected runs (deleting the framework callback).
- **On the benchmarks, the research squad costs requests without adding recall.**
  - Without it, the team found the same on the answer keys at about a quarter of the requests.
  - On the injected set it removed as much (176 against 170) at about a tenth of the requests, but it removed 2 traps where the team removed none.
  - On real projects the squad matters (below).
- The rule-based Manager, broadcast messages, inlined artifacts, no lessons and no coverage guidance stay within two items of the team on the same two seeds (113 of 140). None of them removed a trap.

**Diff audit** (`diff_audit.csv`, `diff_audit_checks.csv`, `diff_audit_types.csv`):
- **Process:**
  - An independent model (`glm-5-3`, never the agents' model) reads every kept code edit of every method and target set, blinded to the method, with 3 votes.
  - Every edit it flags is checked under a written rubric ([docs/experiments.md](docs/experiments.md#v2-diff-audit)):
    - **wrong:** changes behavior that something in the project or its users can trigger;
    - **debatable:** the code is reachable only from outside the project;
    - **fine:** no observable change.
  - Each verdict has a tier:
    - **confirmed:** a targeted test that passes before the edit and fails after, run in that run's own environment; or the UI check; or a rule;
    - **reading (LLM-judged):** read by the coding assistant that ran the evaluation, not a person.
- **Checks:** 561.
  - Wrong: 147. 88 are confirmed. The 59 by reading each record the observed reason no test could run.
  - Debatable: 252, by reading.
  - Fine: 162.
- **Lower bounds, not biased by method.** Only flagged edits are checked, so the wrong counts are lower bounds. The auditor never sees the method, so its flags are not biased by who made the edit, but how loose the bound is differs by method: it voted "no" on 82% of the team's injected edits and 60% of v1's and the single agent's. The checks after a flag saw which run an edit came from; the confirmed tier rests on tests and rules.
- Wrong of the kept code edits, all tiers, with the confirmed count in brackets:

| target | team | no research squad | single agent | v1 |
|---|---|---|---|---|
| injected, all seeds | 18 of 804 (12) | 27 of 825 (22) | 63 of 489 (50) | 48 of 610 (13) |
| real projects (below) | 0 of 14 | 4 of 20 (3) | 17 of 65 (12) | |
| AIDev (6 repositories) | 1 of 10 (1) | | | 8 of 53 (5) |

- **Team against v1 on the injected set:** about the same on the confirmed tier (1.5% [0.8, 1.9] against 2.1% [1.5, 3.8]); lower across all tiers (2.2% [1.5, 2.8] against 7.9% [2.6, 9.0]), though 35 of v1's 48 are readings. On AIDev the team removed about a fifth of v1's code lines (280 against 1,537 in 6 runs), so part of its safety there is caution.
- **No check caught the team's 18 injected wrong edits**: no test, probe or hidden test failed on them.
  - 14 are code that a framework or grader calls by name. 9 are methods (CORAL's eval-viewer `do_GET` and `do_POST`, torch `forward` methods), and 5 are classes (the `KernelBuilder` class of a published kernel demo, dropkit's hatchling build hook).
  - 3 remove dependencies, and 1 changes logic.
  - This is the gap between "everything runs" and "nothing changed" that tests cannot close.
- **The readings are not checked by a person.** The calibration sheet holds 20 blinded checks and has not been filled in yet.

**Framework rule, re-scored** (`inject_rule.csv`):
- Since most of the team's wrong edits were code a framework calls by name, the framework-callback rule now also covers `http.server` handlers, `ast.NodeVisitor`, PyTorch and Lightning modules and hatchling build hooks (#139). On the final data, 14 of the team's 18 injected wrong edits are of that kind, so the rule stays on.
- The runs above were made without it. Re-scoring all 220 injected runs (the hidden test is rerun wherever the rule moves an edit to the suggest lane) gives:

| method | wrong of kept code edits (confirmed), as run → with the rule | traps removed | hidden changed | planted removed |
|---|---|---|---|---|
| team | 18 → 9 (12 → 7) | 0 → 0 | 0 → 0 | 170 → 170 |
| no research squad | 27 → 20 (22 → 17) | 2 → 0 | 2 → 0 | 176 → 176 |
| single agent | 63 → 47 (50 → 34) | 16 → 0 | 16 → 1 | 114 → 114 |
| v1 | 48 → 37 (13 → 8) | 1 → 0 | 1 → 0 | 78 → 78 |

The reported numbers stay as run. The re-score is in-sample: the rule was extended after seeing
these failures and is scored on the same runs, so 18 → 9 is an optimistic estimate; fresh projects
or seeds would test it. The rule moves edits in 38 of the 220 runs. For the team it moves the 9 methods. It does not move the 5 classes a grader or build backend loads by name, the 3 dependency removals or the logic change, because the rule marks methods, not classes. The single agent's
remaining hidden change is slop-guard, seed 1, where the hidden test still fails on the rest of
that run's diff.

**Real-project ablation** (`real_ablation.md`, `real_ablation_runs.csv`): the test of whether
investigation helps on real projects.
- **Setup:** the team, the team without its research squad and the single agent each clean the five case-study projects once (this repository, slop-guard, Skill_Seekers, shotgun, Telegram-Snowball-Sampling), in safe mode, with a 120-minute budget. The single agent's budget starts after its test baseline, and its shotgun run took 144 minutes in all.
- **Columns:**
  - lines removed: net lines removed by the final diffs;
  - reviewer acceptance: the LLM reviewer (an independent model, blinded, 3 votes) judges the kept changes, so its acceptance is LLM-judged;
  - wrong and debatable: the diff audit's verdicts on the kept code edits;
  - UI check: shotgun's.

| method | verdicts | packages kept / rolled back | lines removed | LLM reviewer accepts kept changes (LLM-judged) | wrong of kept code edits (confirmed) | debatable (reading, LLM-judged) | shotgun UI check | LLM requests (mean) | minutes (mean) |
|---|---|---|---|---|---|---|---|---|---|
| team | everything runs 4, nothing applied 1 | 16 / 20 | 315 | 12/14 (2 unsure) | 0 of 14 | 0 | ok | 129.8 | 19.0 |
| no research squad | everything runs 5 | 22 / 35 | 653 | 13/21 (1 unsure) | 4 of 20 (3) | 0 | ok | 15.8 | 35.3 |
| single agent | everything runs 5 | 73 / 9 | 1,020 | 44/65 (8 unsure) | 17 of 65 (12) | 15 | changed (`AttachmentBar`) | 83.2 | 47.1 |
| adaptive investigation | everything runs 4, nothing applied 1 | 19 / 20 | 593 | 12/17 (2 unsure) | 2 of 17 (1) | 0 | ok | 127.2 | 32.5 |

- **On real projects the results suggest the research squad buys safety, not yield.**
  - The audit flagged none of the team's 14 kept code edits (from three projects: it kept no code edit on this repository and applied nothing on slop-guard), so none was found wrong in any tier.
  - Fisher's exact test against the team (`real_ablation_tests.csv`, two-sided): p = 0.13 for the no research squad's 4 of 20 (0.25 for its 3 confirmed), p = 0.03 for the single agent's 17 of 65 (0.11 for its 12 confirmed). Five projects, one run each, and every wrong edit in three of them (this repository, shotgun, Skill_Seekers): this suggests, but doesn't establish, that per-item investigation pays off on real code.
  - Without the squad, the team kept more at an eighth of the requests, but 4 of its 20 kept code edits are wrong. Three are confirmed by targeted tests:
    - it deleted this repository's documented `exp_collect_v2.py`;
    - it deleted a Skill_Seekers function the video pipeline imports;
    - it merged a duplicate through an `src.`-prefixed import that fails once the package is installed.
  - The fourth is by reading: it deleted shotgun's build hook, so the package no longer builds.
- **The single agent removes the most and breaks the most:** 17 of 65 kept code edits are wrong.
  - 12 are confirmed (10 by targeted tests, 2 by the UI check): the Studio messages that print its URL and build commands, two rewritten conditions, a pydantic validator and the command-palette hook in shotgun, and two shotgun widget methods Textual calls by name (`compose`, `watch_state`).
  - 5 are by reading: four core dependencies that Skill_Seekers' `doctor` command imports by name, and shotgun's build hook.
- **Adaptive investigation** (`core.agents.investigate: adaptive`, #145; chain I, run after the others, same budgets): only candidates the rules call uncertain go to an Investigator.
  - **Real projects:** 2 of its 17 kept code edits are wrong, 1 confirmed by a targeted test, where the team has none of 14. Both are edits the no research squad also made: the documented `exp_collect_v2.py` and shotgun's build hook.
  - **Cost:** 127.2 LLM requests per project, against the team's 129.8. On real code nearly every candidate counts as uncertain (378 of 387 on shotgun).
  - **Injected set, seed 1:** it removed 55 of 70 planted items against the team's 57 on the same seed, with no trap and no hidden change, at 78.6 requests per run against 91.8. 4 of its 188 kept code edits are wrong (3 confirmed), against the team's 6 of 275.
  - The default stays `all`.
- **Caveats:**
  - No wrong edit failed a test or probe in its run. Every run ended "everything runs", except slop-guard with the team ("nothing applied").
  - One run per project and 14 to 65 kept code edits per method make this a small sample.
  - The single agent's 120 minutes start after its test baseline (14 minutes on shotgun); the team's start at the beginning of the run.

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

- **No human checked the labels.** The diff audit's reading tier and the review sheets are
  LLM-judged. Three LLM judges from other model families agree with the recorded labels only
  moderately (κ = 0.455, wrong vs not wrong), and of 6 edits confirmed fine they call 4 wrong
  and 2 debatable (v3, Deviation 9).
- **Unused is not unneeded.** The Guard can't check the deletion of a function nothing in the
  project calls: there is nothing to run. `keep_public_api: auto` keeps public names in package
  modules in the suggest lane, and the framework rule keeps framework callbacks there; anything
  else relies on the judge.
- **The framework rule knows a fixed list** (Textual, Django, Flask/FastAPI, Click/Typer, pytest,
  and since #139 `http.server`, `ast.NodeVisitor`, PyTorch, Lightning and hatchling;
  `analysis/frameworks.py`). Callbacks of other frameworks, and classes a grader or plugin
  loader finds by name, look like dead code.
- **"Everything runs" is not "nothing changed".** No test, probe or hidden check caught any of
  the wrong edits the diff audit found in the team's runs: code that only something outside the
  tests reaches (a web handler, a build hook, a documented function) can go with every test
  passing.
- **The framework-rule re-score is in-sample.** The rule was extended after seeing the team's
  wrong edits and re-scored on the same runs, so its 18 → 9 is optimistic until fresh projects or
  seeds test it.
- **The real-project ablation is small.** Five projects, one run each, with the wrong edits
  clustered in three: its differences suggest, but don't establish (Fisher p = 0.13 for the
  research squad).
- **Many audit verdicts are readings.** 59 of 147 wrong verdicts and every debatable one rest on
  reading the code (LLM-judged, by the coding assistant that ran the evaluation), each wrong one
  with the observed reason no test could run. The blinded calibration sheets (20 audit checks, 20
  review items) have not been filled in by a person yet.
- **The audit checks only what its model flags.** Edits the auditor voted "no" (1,223 of 1,784)
  were not checked, so the wrong counts are lower bounds; the auditor is blinded to the method,
  so its flags are not biased by who made the edit, though the share left unchecked differs. It flagged none of the team's 14 real-project edits.
  On the demo app it passed all 11 of the
  single agent's deletions of command functions the app dispatches through `getattr`, though
  those runs failed visible tests.
- **Containers read files through Docker Desktop's file sharing until v2.1.1.** In v2.0 and
  v2.1, the checks that run in containers (the Guard's tests and probes on AIDev and injected
  targets, the hidden checks and the diff audit's targeted tests) saw the workspace through a
  bind mount, which can briefly show a container a deleted file or the old content of a file
  git or an atomic write replaced (2 to 3 of every 60 to 100 such operations in a reproduction,
  idle or under load). Whether any v2 check read a stale file is possible, not measured: the
  logs record outcomes, not file hashes. A stale read hides a change, so it can only have made a
  check pass that should have failed. From v2.1.1 each container holds its own copy, synced and
  checked by hash before every command.
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
