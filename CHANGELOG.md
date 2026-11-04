# Changelog

## Unreleased

Repository restructure; no change in behavior or results (#81–#86, tag `pre-tidy` before it).

- `scripts/` by purpose: `data/`, `experiments/v1/`, `experiments/v2/`, `report/`, `tools/`;
  `reproduce_tables.sh` stays at the top. Script names are unchanged.
- `results/summary/v1/` and `results/figures/v1/` hold the v1 tables and figures, including the
  report tables and figures that were in `docs/report/`; `v2/` folders are for the v2 results.
- CleanSweep Studio (`cleansweep studio`) replaces the Streamlit dashboard, which is removed
  (git history keeps it): every dashboard page has a Studio screen with the same data, and the
  live runner is `python -m cleansweep.live`.
- New docs: `docs/index.md`, `docs/repo_layout.md`, a short `docs/user_guide.md`, and the v2.0
  acceptance checklist `docs/requirements.md`.
- Every regenerated table and figure is byte-identical to `pre-tidy`, and the offline v1 toy
  sweep gives the same report.
- Runs remove their scratch however they end: workspaces, containers, coverage data and the
  probe harness's working folder go on success, on errors and on SIGTERM or SIGHUP; a run's
  start removes what killed runs left (older than 24 hours, owner gone). `cleansweep sweep
  --keep-workspace` keeps the workspace.
- Studio's **Evaluation** screen charts the v2 results from the committed tables: the injection
  benchmark by seed and pooled with CIs, the ablations, the real-project ablation, the diff audit
  by tier and kind, probe strength, the Manager scenarios, LLM-reviewer acceptance and watch.

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
