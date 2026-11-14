# Changelog

## v3.0 (2026-11-14)

Phase 3: the pre-registered evaluation, frozen on 2026-11-13 at 12:00, a simpler Studio, and the
team handoff. v1's and v2's tables are unchanged.

### Results (`results/summary/v3/`, `docs/results.md`)
- **H1, not supported.** On 15 real projects with held-out tests, the team's kept edits were
  wrong far less often than Aider's: 4 of 191 against 4 of 13 confirmed, and 13 against 5
  counting LLM-judged readings. But the team changed held-out tests on 4 of the 10 projects both
  finished, and Aider, which kept almost nothing, on none.
- **H2, not supported, and uninformative.** On 9 of the 10 benchmark repositories, the team with
  and without the resolver produced byte-identical diffs, so the test had no power (#224).
- **H3, supported by a tie.** Batching used 41% of the team's requests, with 16 vs 16 wrong edits
  on the 20 projects both finished (#224). Batching stays off by default.
- **H4, supported, at the threshold.** 27 of 30 repositories ran end to end.
- **Labels:** no human checked them. A panel of three LLM judges agrees with the recorded labels
  at κ = 0.455 (wrong vs not wrong) and is right on 11 of 18 confirmed verdicts (#199).
- **Records:** nine dated deviations are in `docs/preregistration_v3.md` (#179, #191, #194, #196,
  #198). The results came in #217, #221 and #224.

### Evaluation tools
- The runners, tables and figures for INJECT, REAL (with held-out tests), the second model, the
  curve and AUTONOMY, and the audit-miss repeat on the v3 edits (#170–#197).
- `exp_judge_panel.py`, which replaces the human-rating kappa (#199).

### Studio
- A design pass and then a simplification (#218): each screen has one sentence and one main view;
  run screens have one control line, the steps in words and three tabs; the agent graph shows
  names only; Evaluation shows one chart per tab, with the tables on request; Present mode shows
  the caption, the picture and the progress line.
- A short first-run tour and "Try the demo"; help on every screen; axe-clean, with Lighthouse at
  91–100.
- Every user-guide screenshot retaken.
- Large responses are compressed.

### Team
- `docs/team/`: start here, setup, tour, status, tasks, contributions, presentation,
  contributing, handoff and the handoff meeting (#200, #219, #225); one issue per task, and a
  handoff checklist.
- `scripts/tools/install_hooks.sh` installs the pre-push checks.
- The README's toy cleanup runs without Docker (`--sandbox none`).

## v2.1.2 (2026-11-07)

Fixes from AUTONOMY pass 1 of the v3 evaluation (27 of 30 repositories completed), and fixes to the
v3 runners. The INJECT and REAL main runs keep v2.1.1's `clean`; AUTONOMY pass 2 runs on this
release. v2.0's and v2.1's tables are unchanged.

- A project's Git LFS filter never runs in CleanSweep's scratch workspace: a project that
  configures LFS where git-lfs is not installed no longer stops the run (#176).
- Workspace copies keep a project's symbolic links as links: a link loop or a link to a missing
  file no longer stops the run before any cleanup, and a fork no longer turns a link into a file
  (#177).
- v3 runners: INJECT replaces a repository it cannot use from the far end of the reserve (#173);
  the v3 tables read each runner's settled set from every run folder (#174); Aider's inputs reach
  a copied AIDev workspace and its logs come back, and an Aider run without a single LLM request
  is an error rather than a result (#175).

## v2.1.1 (2026-11-06)

Fixes and rules for the v3 evaluation, before any of its main runs. v2.0's and v2.1's tables are
unchanged.

- Containers hold their own copy of the workspace: it is streamed in at the start, its changes
  are pushed in before every command, and the hash of every changed file is checked inside the
  container; a file that still differs fails the command as a stale workspace. Docker Desktop's
  file sharing could show a container a deleted file or a replaced file's old content (#167).
- An optional LLM request limit, `core.llm.max_calls` (#167).
- The v3 pre-registration, `docs/preregistration_v3.md` (#168).
- One 120-minute cap and one 400-request budget for every v3 method, with timed-out runs kept in
  every denominator; REAL baselines run three times and leave flaky tests out; AUTONOMY's
  environment-impossible categories; Aider's changes pulled back from its container; the
  targeted tests open one workspace per seed of the injected toy repository (#168).
- Known limitation added: v2's container checks went through the bind mount, so a stale read is
  possible, not measured (#167).

## v2.1 (2026-11-06)

The known limitations of v2.0 fixed, a polished Studio, and the v3 evaluation's tools. v2.0's
tables and conclusion are unchanged; v3 results go in `results/summary/v3/`.

### Safety and autonomy
- A dynamic-reference resolver: code something reaches by name (entry points, names in config files
  and settings lists, registry decorators, `__all__`, literal `getattr`/`import_module`,
  `__subclasses__()` discovery, classes a framework finds by base class) stays a suggestion with
  its evidence (`reviewer.dynamic_refs`, the agent team only; v1 is unchanged) (#156).
- `clean --sandbox auto|docker|none` and `--untrusted`: a folder that is not a git repository you
  own runs in a Docker container, cut off from the network after the install; a `docker/Dockerfile`
  and a one-line `docker run` quick start (#161).
- `clean` finishes on its own: test-command detection (pytest, unittest, tox, nox, a Makefile
  `test` target), pip/poetry/uv environments and a `src/` layout, a no-tests mode that keeps an edit
  only when probes cover it ("not verified by tests"), a fixed set of verdicts with "stopped:
  <reason>, nothing applied" instead of a stack trace, and `clean --resume` (#160).
- Investigation batching, off by default (`core.agents.investigate_batch`): up to five similar
  candidates per Investigator request, cautious verdicts reused within a run (#157).

### Studio
- One design system (type and spacing scales, state colors with glyphs and labels, light and
  dark, reduced motion); a Home screen ("Clean a folder"); the Project view (the file tree by live
  state, the acting agent on each node); Before / after (both trees, annotated side-by-side diffs,
  a metrics card) (#162).
- Presentation mode (large type, one caption per step, a fixed pace, Space to the next decision)
  and a self-contained HTML export of a run; every shipped recording through every screen in both
  themes in Playwright; all user-guide screenshots retaken (#163).

### Evaluation tools (v3)
- The v3 repository set: a larger license-checked screen of the AIDev pool, split into INJECT,
  REAL and AUTONOMY with an ordered reserve (#159).
- The external baseline: Aider 0.86.2 with the agents' model, a fixed cleanup instruction written
  before any run, the key kept on the host by a relay, judged by the same checks (#158).
- The human-rating packet builder and Cohen's kappa (#155); the audit-miss estimate on v2's
  "no"-voted edits, with the injection key's trap census (#164).
- Runners for out-of-sample injection, real projects with held-out real tests, and the autonomy
  benchmark (#165).
- The v3.0 requirements R17–R30 (#154).

## v2.0 (2026-11-05)

The agent team: `cleansweep clean` and `method=agentic`. v1 (`method=cleansweep`) and every v1
result are unchanged.

### Agent team
- Ten agents in a Manager's phase machine (onboard, baseline, audit, investigate, plan, execute,
  final verify, report), a message board of directed messages, an artifact cache passed by ID,
  and lessons from every rollback (#72, #73, #75, #76).
- The Manager asks the LLM at phase boundaries, after a rollback and at 85% of a budget; hard
  rules keep the last word: budgets, at most two step-backs, never worse than the baseline (#90,
  #106).
- Line-level detectors (debugger calls, debug prints, commented-out code, TODO notes, redundant
  checks) beside v1's; a debugger call behind a condition is only suggested (#76, #124).
- Coverage-guided probes: rounds of LLM-written cases until 90% of the changed lines run; safe mode
  rolls back any probe-found behavior change (#76, #77, #89).
- Thorough mode applies Investigator-safe rewrites the probes verify (#91, #93).
- Formatting is safe only where the project enforces a formatter (#88); an edit that raises is
  skipped instead of ending the run (#125).
- "Everything runs" needs tests that ran at baseline; on SWE-bench the workspace keeps per-test
  results (#118).

### Using it
- `cleansweep clean PROJECT` works on a scratch clone and delivers a branch, a report and patches;
  options for mode, budgets, excludes, test arguments, install and model, or a `.cleansweep.yaml`
  settings file (#73, #78, #122).
- `cleansweep watch` follows a repository's commits and decides when a clean is worth its test
  runs, with its reason (#103).
- A UI snapshot check for Textual apps (#97).

### CleanSweep Studio
- `cleansweep studio`: runs, launch, replay of any run from its event log, step-back view,
  compare, case studies with their LLM review, watch, results and saved sweep reports (#111,
  #115, #117, #120).
- The Streamlit dashboard is removed; Studio has every page it had (#119, #121).

### Experiments (`scripts/experiments/v2/`, `results/summary/v2/`)
- The team against v1 on the answer keys, SWE-bench Tier 1 and a Tier 2 subset, and 6 AIDev
  repositories, with CIs and paired tests (#107, #114).
- A slop-injection benchmark with traps (#104, #110), ablations including a single agent and the
  rule-based Manager (#107), probe strength against v1's mutants and PatchDiff patches (#109),
  Manager decision scenarios (#101), detection by category (#112).
- Five case studies with blinded LLM-reviewer acceptance (an independent model's judgment, not a
  human review) (#92–#100, #105).
- Chaos and property tests and a coverage script (#116).
- The injection benchmark with checked plants (each plant a right answer, each hidden test passing
  before any cleanup), the one-shot baseline shown the planted files, seeds 1–3 with per-seed and
  pooled CIs and paired tests (#128, #131, #146).
- The real-project ablation: the team, no research squad and single agent on the five
  case-study projects, with the LLM reviewer and the UI check (#130, #134–#136).
- A blinded diff audit of every kept code edit, under a written rubric, with two tiers
  (confirmed by a targeted test in the run's own environment, the UI check or a rule; or a
  reading, LLM-judged), kinds and a calibration sheet (#129, #132, #133, #137, #138, #143).
- The framework rule extended to `http.server`, `ast.NodeVisitor`, PyTorch, Lightning and
  hatchling, and re-scored on every injected run next to the numbers as run (#139, #140, #146).
- `core.agents.investigate: all | adaptive | none` (#145), measured on the real projects and the
  injected set (#149, #150): about the team's requests on real code and 2 of 17 kept code edits
  wrong, so the default stays `all`.
- The conclusion worded to the evidence (#151, #152): Fisher's exact test on the real projects
  (`real_ablation_tests.csv`), the injection table on the seeds v1 ran
  (`injection_summary_seeds12.csv`), both tiers against v1, the framework-rule re-score labeled
  in-sample, and the blinded audit's counts as lower bounds its method labels cannot bias.

### Repository and docs
- Restructure into `scripts/{data,experiments/v1,experiments/v2,report,tools}`,
  `results/{summary,figures}/{v1,v2}` and `app/` (#81–#86); byte-identical tables and the same
  offline v1 toy sweep before and after.
- `docs/requirements.md` (R1–R16), `docs/agentic_design.md`, `docs/user_guide.md` with Studio
  screenshots, `docs/repo_layout.md`, and the v2 sections of `docs/experiments.md` and
  `docs/results.md` (#84, #87, #123, #126, #147).
- Runs remove their scratch however they end, and a run's start sweeps orphans;
  `cleansweep sweep --keep-workspace` (#141). `scripts/tools/housekeeping.py` and a repository
  layout test (#142).
- Studio's Evaluation screen: the v2 results by tab, with the tier and LLM-judged labels (#144,
  #148).

## v1.0.3 (2026-10-31)

Experiment scripts default to the archive; no change to the sweep or the results.

- The frozen run copies are gone, and their reports and caches live in `../cleansweep-archive/`.
  `scripts/archive_paths.py` gives the archive folders, and the scripts that read the copies'
  reports default to them: `exp_collect.py`, `exp_aidev_summary.py`, `exp_oneshot_breakages.py`,
  `exp_oneshot_compile.py`, `exp_guard_on_oneshot.py`, `exp_public_api_policy.py`,
  `exp_dependency_check.py`, `exp_framework_callbacks.py` and `exp_shotgun_ui.py`.
- Existing folder flags still override the defaults; scripts that had none get one (`--runs`,
  `--reports`, `--t2-oneshot`, `--t2`, `--t2-rerun`). A default folder that is missing stops the
  script with one line naming the flag to pass.
- An archived AIDev run folder finds its second-model hidden tests in the archive's
  `llm_caches/<copy>/hidden_tests/`.
- Rerun from the archive, every script that runs offline writes byte-identical
  `results/summary/` files.

## v1.0.2 (2026-10-30)

A display fix in the dashboard; no change to the sweep or the results.

- Live sweep: Replay and live runs no longer leave elements of an earlier frame on the page (a
  "Waiting for the Reviewer" line and empty metrics under the stage bar, and a finished check's
  probe differences under the next check's card). Every frame now fills the same slots; the
  Replay test checks for leftovers.

## v1.0.1 (2026-10-30)

Documentation fixes from following the README on a fresh clone; no code changes.

- The quick start saves its report under `results/raw/quickstart/`, where the dashboard lists
  it, instead of `/tmp`.
- The README says why the toy sweep without a key reports a hidden change (the planted
  near-duplicate needs the judge and the probes) and which test markers the offline set leaves
  out.
- `one_shot_compile` in the results table is marked as a re-score, not a `--method`.

## v1.0 (2026-10-30)

The first release: the system, the experiments and their results as reported in our final
report. Numbers are in `results/summary/`; [docs/results.md](docs/results.md) has the details and
[docs/experiments.md](docs/experiments.md) how each was made.

### Reviewer
- Detectors for leftover files, dead code (vulture, checked against the code graph), exact and
  near duplicates, one-use wrappers, unused imports and dependencies, security findings (report
  only) and formatting, each with evidence and a safe or suggest lane.
- LLM judge in three modes: `gatekeeper` (default; its veto moves an item to the suggest lane),
  `advisory` and `off` (#4, #10).
- Over-engineering review, report only; "can't happen" findings on lines a test runs are dropped
  (#11, #15, #19, #20).
- Review scope: only the code an agent wrote on SWE-bench and AIDev targets (#24, #43, #53).
- v1.0 defaults: `keep_public_api: auto` keeps dead code on public names in package modules in the
  suggest lane (#52); `framework_callbacks: on` does the same for methods Textual, Django,
  Flask/FastAPI, Click/Typer or pytest call by name (#56).
- `reviewer.exclude` leaves folders alone, the over-engineering review included (#59, #66).
- Format edits follow the project's own ruff settings (#63).

### Guard
- Applies each batch in a scratch git workspace and keeps it only if the changed files compile and
  import, the tests give the same results, and formatting leaves the syntax tree unchanged; a
  failing batch is split until the bad edit is found, and a single edit gets one repair try.
- Differential probes: LLM-written calls to the old and new code on the same inputs, as a script
  or inside the project's own test runner (#21, #35).
- Dependency removals are checked by rerunning the tests with the package uninstalled, in AIDev
  containers; elsewhere they are marked "checked statically only" (#61, #62).

### Workspaces, workflow and interfaces
- Local folders, SWE-bench Docker images with an agent's patch, and AIDev containers that install
  the project and lose their network before any project code runs (#23, #32, #39, #46).
- `run_sweep(..., on_event=None)` reports each step; `build_plan` and `judge_items` take the run's
  config (#57, #58). Contract changes are additive.
- LLM client with a disk cache, retries on gateway errors, and failures recorded in the run
  stats; a failed judge or repair request no longer stops a sweep (#14, #44, #47).

### Dashboard and demo
- Streamlit dashboard: report viewer, Live sweep with Replay, Scheduler, Baselines, Data and
  Guard pages (#7, #40).
- Demo app with planted problems, an agent-style feature patch and a timed script; three demo
  recordings ship in `demo/replay/`, so Replay works offline (#13, #16, #65).

### Experiments
- Baselines: `guard_tests_only`, `tools_only`, `one_shot_llm` and its compile-check and one-retry
  variants (#28, #36, #51).
- SWE-bench Tier 1 and Tier 2 with PatchDiff hidden tests; AIDev sweeps on 20 repositories with
  second-model hidden tests; Guard strength by mutation; the Guard as a filter on one-shot edits
  (#25, #30, #41, #42, #45, #49, #64).
- Policy re-scores, framework callbacks, a headless UI check and a dependency re-check on the
  finished AIDev runs (#64); a self-sweep of this repository (#60, #66).
- Scheduler replay, removal-request mining, the ranker and Reviewer detection (#31, #33, #37).
- `scripts/reproduce_tables.sh` rebuilds every aggregate table and figure offline from the
  committed per-run CSVs (#67).
