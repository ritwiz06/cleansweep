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
│                                         e2e/ (Playwright); dist/ and node_modules/ are ignored
├── demo/                                 bookstore demo app (shop_app/), its answer key and hidden
│                                         tests, feature.patch, prepare_demo.sh, run_demo.md,
│                                         replay/ (recorded runs for offline Replay)
├── scripts/
│   ├── data/                             data_*.py: downloads, tier splits, AIDev selection, scope,
│   │                                     mining, data summaries
│   ├── experiments/v1/                   v1 runners and table builders (exp_*.py), archive_paths.py,
│   │                                     shotgun_ui_harness.py
│   ├── experiments/v2/                   v2 runs: exp_agentic.py, exp_case_study.py
│   ├── report/                           make_assets.py (report tables and figures), pipeline.mmd
│   ├── tools/                            check_contracts.py, voyager_ping.py, core_make_samples.py,
│   │                                     make_recording.py (Studio recordings), coverage.sh
│   └── reproduce_tables.sh               rebuilds the aggregate tables and figures offline
├── results/
│   ├── summary/v1/                       committed v1 tables (CSV and Markdown)
│   ├── summary/v2/                       v2 tables (Phase 4)
│   ├── figures/v1/                       committed v1 figures
│   ├── figures/v2/                       v2 figures (Phase 4)
│   ├── data_summary/                     mined-data summaries (taxonomy, rules, funnel, detection);
│   │                                     the v2 knowledge base reads them
│   └── raw/                              per-run reports (git-ignored; archived copies in
│                                         ../cleansweep-archive/raw/)
├── data/splits/                          committed tier and repository splits (data/raw and
│                                         data/processed are git-ignored)
├── docs/                                 index, user guide, architecture, agentic design,
│                                         requirements, experiments, results, this file
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
- A new experiment script goes in `scripts/experiments/v2/`; its tables in `results/summary/v2/`
  and its figures in `results/figures/v2/`; `scripts/reproduce_tables.sh` rebuilds them.
- Raw run output goes in `results/raw/<folder>/` (git-ignored) and is archived before a release.
- A test goes in the `tests/` folder that mirrors the code it tests.
- Local notes (status docs, report sources, scratch) live in `.notes/`, which git never sees.
