# Repository layout

Restructured on 2026-11-01 (tag `pre-tidy` marks the layout before). Moves only: every
reported table and figure rebuilds byte-identical in its new place.

```
cleansweep/
├── README.md, CHANGELOG.md, CODEOWNERS   overview and quick start; release notes; review owners
├── pyproject.toml                        package metadata, ruff and pytest settings
├── requirements.txt, requirements/       install entry point; per-area requirements it includes
├── configs/                              settings: base.yaml (core, guard, agents), data.yaml,
│                                         exp.yaml, reviewer.yaml
├── .github/workflows/                    CI definition (lint, offline tests, contract check)
├── src/cleansweep/                       the package
│   ├── core/                             contracts (models.py, contracts.py), config, JSON io
│   ├── llm/                              LLM client with disk cache; FakeLLM for tests
│   ├── sandbox/                          workspaces: local folders, SWE-bench and AIDev containers
│   ├── analysis/                         code graph, duplicate finder, frameworks, features
│   ├── reviewer/                         detectors, line-level detectors, rewrites, LLM judge
│   ├── guard/                            applies edits, verifies them (tests, AST, probes), rolls back
│   ├── ranking/                          safe-to-remove scores
│   ├── scheduler/                        batching with bisection, sweep policies, replay
│   ├── workflow/                         run_sweep (v1 pipeline; dispatches method=agentic)
│   ├── agents/                           v2 agent team: Manager, squads, board, cache, prompts/
│   ├── eval/                             baselines, hidden checks, metrics, mutation, statistics
│   ├── data/                             SWE-bench, PatchDiff and AIDev loaders, splits
│   ├── mining/                           review-comment mining: requests, taxonomy, rules
│   ├── live.py                           runs one v1 sweep and logs each step (Studio's v1 sweeps)
│   ├── runlog.py                         reads recorded runs: v1 event logs, sweep reports, scores
│   └── cli.py                            `cleansweep sweep | plan | show | clean | watch | studio`
├── app/
│   └── studio/                           CleanSweep Studio (replaced the dashboard, R16): server.py
│       │                                 (FastAPI app, `cleansweep studio`), files.py (allowed
│       │                                 roots, redaction), runs.py, jobs.py, data.py, worker.py
│       └── frontend/                     React + TypeScript (Vite): src/ (screens/, components/,
│                                         state/ with the event folds and their vitest tests),
│                                         e2e/ (Playwright; guide.spec.ts takes the user guide's
│                                         screenshots); dist/ and node_modules/ are ignored
├── docker/                               Dockerfile: CleanSweep in a container (`clean --sandbox`,
│                                         the `docker run` quick start)
├── demo/                                 bookstore demo app (shop_app/), its answer key and hidden
│                                         tests, feature.patch, prepare_demo.sh, run_demo.md,
│                                         replay/ (recorded runs for offline Replay)
├── scripts/
│   ├── data/                             data_*.py: downloads, tier splits, AIDev selection, scope,
│   │                                     mining, data summaries
│   ├── experiments/v1/                   v1 runners and table builders (exp_*.py), archive_paths.py,
│   │                                     shotgun_ui_harness.py
│   ├── experiments/v2/                   v2 runs: exp_agentic.py, exp_case_study.py
│   ├── experiments/v3/                   v3 runs: methods_v3.py, exp_inject_v3.py, exp_real_v3.py,
│   │                                     exp_autonomy.py, exp_external.py (Aider: prompts/ holds its
│   │                                     fixed instruction, aider/ its image), exp_human_packet.py,
│   │                                     exp_human_kappa.py
│   ├── report/                           make_assets.py (report tables and figures), pipeline.mmd
│   ├── tools/                            check_contracts.py, voyager_ping.py, core_make_samples.py,
│   │                                     make_recording.py (Studio recordings), coverage.sh,
│   │                                     housekeeping.py (see below)
│   └── reproduce_tables.sh               rebuilds the aggregate tables and figures offline
├── results/
│   ├── summary/v1/                       committed v1 tables (CSV and Markdown)
│   ├── summary/v2/                       committed v2 tables (CSV and Markdown)
│   ├── summary/v3/                       committed v3 tables (CSV and Markdown)
│   ├── figures/v1/                       committed v1 figures
│   ├── figures/v2/                       v2 figures (empty: the v2 results are tables)
│   ├── figures/v3/                       v3 figures (scripts/report/make_figures_v3.py)
│   ├── data_summary/                     mined-data summaries (taxonomy, rules, funnel, detection);
│   │                                     the v2 knowledge base reads them
│   └── raw/                              per-run reports (git-ignored; archived copies in
│                                         ../cleansweep-archive/raw/)
├── data/splits/                          committed tier and repository splits (data/raw and
│                                         data/processed are git-ignored)
├── docs/                                 index, user guide, architecture, agentic design,
│                                         requirements, experiments, results, this file;
│                                         images/studio/ (the user guide's screenshots)
└── tests/                                mirrors the code: one folder per package (core/, llm/,
    │                                     sandbox/, analysis/, reviewer/, guard/, ranking/,
    │                                     scheduler/, workflow/, agents/, eval/, data/, mining/)
    ├── app/                              studio/ (API tests; the frontend checks under the slow
    │                                     marker) and the demo app test
    ├── scripts/                          data/, experiments/v1/, test_reproduce_tables.py
    └── fixtures/                         toy repo, its answer key and hidden tests, sample report
                                          and plan, a small results set, studio/ (a case study
                                          and a watch folder)
```

Where things go:
- A new experiment script goes in `scripts/experiments/v3/`; its tables in `results/summary/v3/`
  and its figures in `results/figures/v3/`; `scripts/reproduce_tables.sh` rebuilds them. v1's and
  v2's folders stay as they were released.
- Raw run output goes in `results/raw/<folder>/` (git-ignored) and is archived before a release.
- A test goes in the `tests/` folder that mirrors the code it tests.
- Local notes (status docs, report sources, scratch) live in `.notes/`, which git never sees.
- `tests/test_repo_layout.py` (in the pre-push checks and CI) fails when a tracked file sits
  outside the folders above or is named like scratch (`tmp_*`, `*_old`, `*_backup*`, `scratch*`,
  `*.bak`, `untitled*`, `debug_*`), unless its allowlist names the file with a reason.

## Housekeeping

`python scripts/tools/housekeeping.py` lists what a pass would do; `--apply` does it, prints the
space freed and appends a line to `.notes/housekeeping.log`. It touches only the repository's
parent folder and the temp folder's CleanSweep scratch (`cleansweep/ws/` and the `cs_*` folders).

- Kept: the repository, `../cleansweep-archive/` and its tarball, the frozen run clones, the
  case-study folder's live chain scripts and logs, every `results/raw/` folder that feeds a
  table, the Docker images, and `.notes/`'s docs, report, submission and calibration sheets.
- Removed when no running job uses it (no process works in it, no running container mounts it,
  no command line names it) and it is older than `--min-age-hours` (2): workspaces of finished
  runs, the temp folder's `cs_*` scratch, stopped `cs-*` containers and dangling volumes, caches
  (`__pycache__`, `.pytest_cache`, `.ruff_cache`, Playwright output, coverage data, the
  frontend's `dist/`, which Studio rebuilds), and backups whose exact content is committed.
- Archived, then removed, when older than `--archive-age-hours` (24): runs set aside after a
  sleep, finished chains' scripts and logs, finished pushes' logs, `.notes` files nothing cites,
  and every UI-review set but the latest. Each copy is checked, added to the archive's
  `SHA256SUMS`, and the archive's `tools/verify_archive.py` must pass before the original goes.
