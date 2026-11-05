# Experiments

This page lists the experiments behind the CleanSweep results: how to run each one, which code
version produced the reported numbers, what it reads and writes, how long it took and which LLMs
it used. The pipeline is described in [architecture.md](architecture.md); the results are in the
README, [results.md](results.md), `results/summary/v1/` and `results/summary/v2/`.

- **Code version** is the commit the reported runs used. Long runs ran in a separate clone frozen
  at that commit ("main at 07a4dad"); runs made from a working branch name its pull request.
  "Not recorded" means our run log does not say.
- Per-run reports go to `results/raw/<folder>/` (gitignored). Files in `results/summary/v1/`,
  `results/summary/v2/`, `results/data_summary/` and `results/figures/v1/` are committed.
- v1's frozen clones are gone; their reports and caches are kept outside the repository in
  `../cleansweep-archive/` (`raw/<clone>/results_raw/<folder>/`, `llm_caches/<clone>/`). The raw
  reports are not published because they contain third-party code. Scripts that read them
  default to the archive folders (`scripts/experiments/v1/archive_paths.py`); their folder flags override that,
  and a default folder that is missing stops the script with the flag to pass.
- Runtimes are wall-clock on the [reference machine](#requirements) and include contention when
  two jobs shared it. Model names are those our LLM endpoint served at the time.
- Run every command from the repository root.

## Overview

| Experiment | Scripts | Code version | Committed summary |
|---|---|---|---|
| [Answer keys](#answer-keys-toy-repo-and-demo-app) | `cleansweep.live` | main, 2026-10-26/27 (not recorded) | `main_results.csv` |
| [Judge model checks](#judge-model-checks) | `cleansweep sweep` | main, 2026-10-24 (not recorded) | `results/summary/v1/judge_*.md` |
| [SWE-bench Tier 1](#swe-bench-tier-1) | `exp_swebench.py` | main at 9c536a5, plus reruns | `main_results.csv` |
| [SWE-bench Tier 2](#swe-bench-tier-2) | `exp_swebench.py` | main at 07a4dad and 83e3b00 | `main_results.csv` |
| [AIDev sweeps](#aidev-sweeps) | `exp_swebench.py`, `exp_aidev_summary.py` | main at 06d2ab6, e57cf92, c8ae076 | `main_results.csv`, `aidev_sweeps.csv` |
| [Guard strength](#guard-strength) | `exp_guard_strength.py` | PR #30 and #35 branches; main at 83e3b00 | `guard_strength.csv` |
| [One-shot baselines](#one-shot-baselines) | `exp_swebench.py`, `exp_oneshot_compile.py`, `exp_oneshot_breakages.py` | see section | `main_results.csv`, `oneshot_compile.csv`, `oneshot_breakages.csv` |
| [Guard on one-shot](#guard-on-one-shot) | `exp_guard_on_oneshot.py` | main at 2ad7387 | `guard_on_oneshot.csv` |
| [Scheduler replay](#scheduler-replay-and-trade-off) | `exp_replay.py`, `exp_scheduler_tradeoff.py` | PRs #31–#33 and #37 | `scheduler_replay.csv`, `scheduler_tradeoff.csv` |
| [Ranker and detection](#ranker-and-reviewer-detection) | `data_aidev_mine.py`, `exp_train_ranker.py`, `exp_reviewer_detection.py` | PRs #31–#33 and #37 | `ranker_cv.csv`, `reviewer_detection.csv` |
| [Policy re-scores](#policy-re-scores) | `exp_public_api_policy.py` | main at f2d0bce; PR #64 (merged as ff98c90) | `aidev_public_api_policy.csv`, `aidev_framework_rule.csv`, `aidev_final_policy.csv` |
| [Framework callbacks, UI check](#framework-callbacks-and-shotgun-ui-check) | `exp_framework_callbacks.py`, `exp_shotgun_ui.py` | PR #64 (merged as ff98c90) | `framework_callbacks.csv`, `shotgun_ui.csv` |
| [Dependency re-check](#dependency-re-check) | `exp_dependency_check.py` | PR #62 branch (a5e3353, merged as a439dcd) | `aidev_dependency_check.csv` |
| [Self-sweep](#self-sweep) | `exp_self_sweep.py` | main at a439dcd | `self_sweep.csv` |
| [v2 case studies](#v2-case-studies-and-llm-reviewer-acceptance) | `exp_case_study.py`, `exp_llm_review.py` | 39ba2e2, 81da3ea, 1b2f899 | `llm_review_acceptance.csv`, `mining_llm_precision.csv` |
| [v2 Manager scenarios](#v2-manager-scenarios) | `exp_manager_scenarios.py` | main at 015a98f | `manager_scenarios.csv` |
| [v2 team vs v1, ablations](#v2-agentic-vs-v1-and-the-ablations) | `exp_eval.py`, `exp_collect_v2.py`, `exp_tables_v2.py` | main at c68fcdc and 7237ccc | `eval_runs.csv`, `eval_table`, `eval_paired`, `ablations` |
| [v2 probe strength](#v2-probe-strength-patchdiff-recall-mutation-score) | `exp_probe_strength.py` | main at f84d568 | `probe_strength.csv`, `probe_strength_vs_v1.csv` |
| [v2 detection](#v2-detection-by-category-on-aidev) | `exp_detection.py` | PR #112 (merged as c003ca0) | `detection.csv` |
| [v2 slop injection](#v2-slop-injection-benchmark) | `exp_inject.py`, `exp_tables_v2.py` | main at f84d568; 106c952 (plant checks, seeds 2 and 3) | `injection.csv`, `injection_summary.csv`, `injection_seeds`, `injection_paired`, `ablations` |
| [v2 real-project ablation](#v2-real-project-ablation) | `exp_case_study.py --ablation`, `exp_real_ablation.py` | 106c952 (#128) | `real_ablation_runs.csv`, `real_ablation` |
| [v2 diff audit](#v2-diff-audit) | `exp_diff_audit.py`, `exp_audit_confirm.py`, `exp_audit_rubric.py`, `audit_loop.sh`, `confirm_batch.sh` | ee10e14 (#132) and later | `diff_audit_checks.csv`, `diff_audit.csv`, `diff_audit_types.csv` |
| [v2 framework rule re-scored](#v2-the-extended-framework-rule-re-scored) | `exp_rule_rescore.py` | #139 and later | `inject_rule.csv` |
| [v2 watch mode](#v2-watch-mode) | `exp_watch.py` | PR #103 (merged as 12caf01) | `watch_replay.csv` |

## Experiments

Methods, as `exp_swebench.py --methods` names them: `cleansweep-gatekeeper`,
`cleansweep-advisory`, `guard_tests_only` (advisory judge, no probes), `tools_only`,
`one_shot_llm` (these five are the default) and `one_shot_retry`. `exp_collect.py` derives
`one_shot_compile` from existing results.

### Answer keys: toy repo and demo app

- **Run:** one recorded live run per method and target. Pass the target as a relative path and a
  `--run-id` dated 20261026 to 20261029; `exp_collect.py` reads only those recordings.
  ```bash
  bash demo/prepare_demo.sh --with-feature    # builds .cleansweep/demo/shop_app
  python -m cleansweep.live --target tests/fixtures/toy_repo --method cleansweep \
      --judge-mode advisory --run-id 20261026_toy_advisory_probes
  ```
  Recorded on both targets: `cleansweep` (gatekeeper and advisory), `guard_tests_only`,
  `tools_only` on 2026-10-26; `one_shot_llm` on 2026-10-27. Commits not recorded.
- **Inputs:** `tests/fixtures/toy_repo` (13 planted items in `toy_repo_expected.json`, hidden
  tests in `toy_repo_hidden/`); `demo/shop_app` plus `demo/feature.patch` (7 planted items,
  hidden tests in `shop_app_hidden/`). The hidden tests are hand-written.
- **Outputs:** `results/raw/live/<run_id>/` (`events.jsonl`, `report.json`); the `toy` and `demo`
  rows of `main_results.csv`. Three demo recordings ship in `demo/replay/` with repo-relative
  paths, so Studio's Replay works on a fresh clone: the advisory run with the v1.0
  defaults (`20261030_demo_feature_advisory_v1`, main at f708d87, 6.3 min cold, outcome 7/7; not
  a `main_results.csv` row), the first run with probes, and the run before the probes existed.
- **Runtime:** 4–8 s from the LLM and probe caches; 1.5–5 min with live judge requests; 8–21 min
  for the first runs with live probe requests. **Models:** judge, repair, probes and one-shot
  `qwen36-35b-a3b` (probes and one-shot with reasoning off); the earliest toy runs in
  `results/raw/toy/` used `qwen36-27b` as the judge.

### Judge model checks

- **Run:** one gatekeeper sweep per model and run, the model set through `VOYAGER_MODEL` and a
  separate LLM cache file per run (`core.llm.cache_path`) so every run makes live requests. The
  loop that drove the runs is not in the repository; each run is equivalent to
  ```bash
  VOYAGER_MODEL=<model> CLEANSWEEP_JUDGE_MODE=gatekeeper python -m cleansweep sweep \
      --target tests/fixtures/toy_repo --seed <s> --out results/raw/judge_check/<model>__s<s>.json --hidden
  ```
  The demo check used `--target demo/shop_app` with `CLEANSWEEP_OVERENGINEERING=0`. The seed only
  labels repeat runs; the judge never receives it. Main checkout, 2026-10-24; commits not recorded.
- **Outputs:** `results/raw/judge_bakeoff/`, `judge_check/`, `demo_check/`; tables
  `results/summary/v1/judge_checks.md` and `judge_check_runs.md` (`python scripts/report/make_assets.py`).
- **Runtime:** 1.5–9 min per sweep; judge requests took 40–260 s each, depending on endpoint load.
- **Models:** first comparison, one run each: `qwen36-27b`, `qwen36-35b-a3b`, `qwen3-235b-a22b`,
  `qwen3-coder-next`, `kimi-k2-7-code`. Answer-key check, three runs each at temperature 0:
  `qwen36-35b-a3b`, `qwen36-27b`, `kimi-k2-7-code`. Demo: `qwen36-35b-a3b`, `qwen36-27b`.
  `qwen36-35b-a3b` is the judge in every later experiment.

### SWE-bench Tier 1

- **Run:** `python scripts/experiments/v1/exp_swebench.py --tier data/splits/swebench_tier1.json --out results/raw/swebench_t1 [--methods ...] [--resume]`
- **Code version:** four methods at main 9c536a5 (2026-10-26; the script was then
  `exp_swebench_tier1.py`). Gatekeeper rerun after the judge-signal fix on the PR #29 branch
  (merged as 1fd53e9); `one_shot_llm` with JSON replies on the PR #36 branch (merged as a2e0883);
  `one_shot_retry` at main 081fe4d.
- **Inputs:** `data/splits/swebench_tier1.json`: 10 agent patches on 4 instances (4 images), 3 of
  which differ from the developer's fix. Hidden checks: the instance's FAIL_TO_PASS and
  PASS_TO_PASS tests plus up to 10 PatchDiff test files per patch (1–38 stable tests per patch).
- **Outputs:** `results/raw/swebench_t1/<instance>__<agent>__<method>.json`, `log.txt`; the
  `swebench_t1` rows of `main_results.csv`.
- **Runtime:** 79 min for the first 40 runs (four methods), 22 min for the gatekeeper rerun, about
  35 min for `one_shot_llm`. **Models:** judge and repair `qwen36-35b-a3b`; probes and one-shot
  the same with reasoning off.

### SWE-bench Tier 2

- **Run:** `python scripts/experiments/v1/exp_swebench.py --tier data/splits/swebench_tier2.json --out results/raw/swebench_t2 [--resume]`
- **Code version:** main at 07a4dad (after PR #28), 2026-10-26/27. A second clone at 83e3b00 (after
  PR #39) ran `one_shot_llm` on all reported patches (`results/raw/swebench_t2_oneshot/`) and every
  method on the 4 patches that failed under 07a4dad (`results/raw/swebench_t2_rerun/`).
  `one_shot_retry` ran at 081fe4d.
- **Inputs:** `data/splits/swebench_tier2.json`: 60 patches on 21 instances in 11 repositories
  (Tier 1 included), 18 differ from the developer's fix. Results use 57: the three
  `psf__requests-2317` patches are left out (`exp_collect.py --exclude` default) because that
  project's tests call a live web service (two took 2.7 and 3.5 h; the third was stopped). PatchDiff tests had to be stable
  over 2 runs in the first run, 3 from PR #39 on. `swebench_tier3.json` (435 patches) was not run.
- **Outputs:** per-run reports in the three folders; the `swebench_t2` rows of `main_results.csv`.
- **Runtime:** first run about 28 h, including a 3 h pause and about 6.5 h on the requests
  patches; one-shot rerun 1 h 47 min; the 4 rerun patches 27 min. Median minutes per patch:
  gatekeeper 2.2, advisory 1.3, `guard_tests_only` 1.4, `tools_only` 0.8, `one_shot_llm` 1.4.
  **Models:** as in Tier 1.

### AIDev sweeps

- **Run:**
  ```bash
  python scripts/experiments/v1/exp_swebench.py --tier data/splits/aidev_repos.json --out results/raw/aidev_sweeps --resume
  python scripts/experiments/v1/exp_swebench.py --tier data/splits/aidev_repos.json --out results/raw/aidev_sweeps --hidden-only
  python scripts/data/data_aidev_scope.py --backfill results/raw/aidev_sweeps   # reports from before PR #53
  python scripts/experiments/v1/exp_aidev_summary.py --runs results/raw/aidev_sweeps [rerun folders ...]
  ```
  `--hidden-only` reruns the hidden checks of reports whose diff did not apply.
- **Code version:** main at 06d2ab6 (after PR #44) from 2026-10-28, one worker, then two (the 15
  faster and the 5 slowest repositories). Reruns at main e57cf92 (after PR #48): one repository's
  hidden checks, two `guard_tests_only` runs that had failed on an LLM timeout, and shotgun's five
  runs (`results/raw/aidev_scoped/`). At main c8ae076 (after PR #53): opendbc and
  pytorch_connectomics with a longer scope history and `keep_public_api: "off"`
  (`results/raw/aidev_window/`).
- **Inputs:** `data/splits/aidev_repos.json`: 20 runnable repositories at their recorded head sha,
  fastest test suite first. One runnable repository is left out of our released data files. The
  sweep needs the clones and cached histories ([Getting the data](#getting-the-data)) and stops if
  a history is missing. Hidden checks: pytest tests that a second model writes for the public
  functions and methods of up to 6 agent files, once per repository (`.cleansweep/hidden_tests/`),
  kept when stable over 3 runs.
- **Outputs:** `results/raw/aidev_sweeps/<owner>__<name>__<method>.json`, `log.txt`, `errors/`;
  the `aidev` rows of `main_results.csv` (20 repositories × 7 methods); `aidev_sweeps.csv`, `.md`.
- **Runtime:** about two days of wall time with at most two jobs. The 15 faster repositories took
  about 21 h (20–90 min each for five methods); shotgun gatekeeper 3.2 h, advisory 11.1 h,
  `guard_tests_only` 13 h; pytorch_connectomics 3.5 h and opendbc 1.5 h for five methods.
  **Models:** judge, repair, probes and one-shot `qwen36-35b-a3b`; hidden tests `glm-5-3`.

### Guard strength

Mutants, PatchDiff recall (agent patch against the developer's fix, where they differ) and false
alarms on identical copies, all through `guard.verify`.

- **Run:**
  ```bash
  python scripts/experiments/v1/exp_guard_strength.py --local tests/fixtures/toy_repo .cleansweep/demo/shop_app --resume
  python scripts/experiments/v1/exp_guard_strength.py --tier data/splits/swebench_tier1.json --probe-mode direct --resume
  python scripts/experiments/v1/exp_guard_strength.py --tier data/splits/swebench_tier1.json --probe-mode runner --resume
  ```
  The demo target needs `bash demo/prepare_demo.sh --with-feature` first. The Tier 2 part (runner
  mode, the 47 reported patches outside Tier 1) used `--tier` with Tier 2 patches; the exact
  invocation is not recorded.
- **Code version:** toy, demo and Tier 1 (direct) on the PR #30 branch (merged as 2442965),
  2026-10-26; direct against runner mode on Tier 1, and Tier 2 recall, on the PR #35 branch
  (merged as a5243dc), 2026-10-27; Tier 2 mutants and false alarms at main 83e3b00.
- **Inputs:** up to 20 mutants per answer-key target; up to 5 per SWE-bench patch, in functions
  the agent wrote (39 on Tier 1, 189 on Tier 2 beyond Tier 1).
- **Outputs:** `results/raw/guard_strength/<set>__<target>__<mode>.json`; `guard_strength.csv`;
  `results/figures/v1/guard_strength.png` (from `exp_tables.py`).
- **Runtime:** Tier 1 runner mode about 30 min (Django patches 4–5 min each, 2–3 min in direct
  mode); Tier 2 about 2 h, plus 1.5 h to redo two patches whose probe requests failed; toy and
  demo not recorded. **Models:** probe requests `qwen36-35b-a3b` with reasoning off; no judge.

### One-shot baselines

`one_shot_llm` sends the agent's files (all `.py` files on local targets, within 60k characters)
in one request and applies the JSON reply (files to delete, new file contents) unchecked.
`one_shot_compile` discards a diff whose rewritten files don't compile; `one_shot_retry` sends the
compile errors back once and applies the second reply.

- **Run:**
  ```bash
  python scripts/experiments/v1/exp_swebench.py --tier <split> --out <folder> --methods one_shot_llm --resume
  python scripts/experiments/v1/exp_oneshot_compile.py        # no LLM, no Docker
  python scripts/experiments/v1/exp_swebench.py --tier <retry split> --out results/raw/oneshot_retry --methods one_shot_retry
  python scripts/experiments/v1/exp_oneshot_breakages.py      # what breaking diffs changed; Docker, no LLM
  ```
  The retry split (not committed) holds the 7 patches whose first reply didn't compile: 3 of
  `sympy__sympy-11618`, 3 of `sphinx-doc__sphinx-7454`, 1 of `scikit-learn__scikit-learn-10844`.
  Elsewhere `one_shot_retry` equals `one_shot_llm`, since its first request is the same.
- **Code version:** `one_shot_llm` as in the grids above; `exp_oneshot_compile.py` from PR #51
  (081fe4d), rerun at 20 AIDev repositories on the PR #64 branch; `one_shot_retry` at
  main 081fe4d, 2026-10-29; breakages on the PR #42 branch (merged as 2ad7387).
- **Inputs:** the Tier 1, Tier 2 and AIDev reports; `guard_on_oneshot.csv` (the Guard's compile
  step on SWE-bench); the AIDev clones at their head sha (compiled with Python 3.11).
- **Outputs:** `results/raw/oneshot_retry/`; `oneshot_compile.csv`, `oneshot_breakages.csv`, `.md`;
  the `one_shot_*` rows of `main_results.csv`.
- **Runtime:** retry 2.5–3.7 min per patch (one new request each); breakages about 10 min per pass;
  compile check not recorded. **Models:** `qwen36-35b-a3b`, reasoning off, seed 0.

### Guard on one-shot

`verify(agent patch, agent patch + one-shot diff)` with tests and runner-mode probes, for every
SWE-bench patch where `one_shot_llm` applied edits.

- **Run:** `python scripts/experiments/v1/exp_guard_on_oneshot.py --resume` at main 2ad7387 (after PR #42), 2026-10-27/28.
- **Inputs:** the Tier 1 and Tier 2 reports: 57 one-shot runs with edits (8 Tier 1, 49 Tier 2; the
  Tier 1 diffs repeat in Tier 2, so 49 are distinct).
- **Outputs:** `results/raw/guard_on_oneshot/`; `guard_on_oneshot.csv`, `.md`.
- **Runtime:** 46 min; 20–45 s for most patches, several minutes for Django and scikit-learn.
  **Models:** probe requests `qwen36-35b-a3b` with reasoning off.

### Scheduler replay and trade-off

- **Run:** `python scripts/experiments/v1/exp_replay.py [--points 40]`, then `python scripts/experiments/v1/exp_scheduler_tradeoff.py`.
  Replay from PRs #31–#33 (2026-10-26), trade-off from PR #37 (merged as aa15e60, 2026-10-27);
  exact commits not recorded.
- **Inputs:** the 20 repositories, the last 300 first-parent commits of each (4,695 commits, 626
  from agent pull requests), static detectors only, measured at up to 40 commits plus the last.
- **Outputs:** `scheduler_replay.csv`, `scheduler_curves.csv`, `scheduler_tradeoff.csv`,
  `results/figures/v1/scheduler_tradeoff.png`; per-commit cache in `data/processed/aidev_slop/`.
- **Runtime:** not recorded. **Models:** none.

### Ranker and Reviewer detection

Review comments mined for removal requests and mapped to code units; the units train the ranker
and score what the detectors flag.

- **Run:**
  ```bash
  python scripts/data/data_aidev_mine.py mine
  python scripts/data/data_aidev_mine.py labels --scope requests --hours 1
  python scripts/experiments/v1/exp_train_ranker.py && python scripts/experiments/v1/exp_ranker_report.py
  python scripts/experiments/v1/exp_reviewer_detection.py && python scripts/data/data_detection_by_category.py
  ```
  Mining, labels, ranker and detection from PRs #31–#33 (2026-10-26); ranker report and detection
  by category from PR #37 (2026-10-27). Exact commits not recorded.
- **Inputs:** 6,330 human review comments on `.py` files, 792 keyword matches, 535 removal requests
  confirmed by the LLM in 102 repositories. Labels: 9,416 units, 262 requests, 79 repositories,
  by static analysis only.
- **Outputs:** `data/processed/aidev_{requests,labels,detection}.parquet`;
  `results/data_summary/aidev_taxonomy.csv`, `aidev_rules.csv`, `detection_by_category.csv`;
  `ranker_cv.csv`, `ranker_status.json`, `ranker_report.md`, `reviewer_detection.csv`,
  `results/figures/v1/ranker_reliability.png`; the model in `results/models/ranker.joblib`
  (gitignored, not used by default).
- **Runtime:** labels capped at 1 h; the rest not recorded. **Models:** mining `qwen36-35b-a3b`
  with reasoning off (40 requests of 20 comments); no LLM elsewhere.

### Policy re-scores

The AIDev CleanSweep runs re-scored without new sweeps: edits a Reviewer policy would have kept in
the suggest lane are reversed out of each final diff, lines are recounted, and with `--run` the
hidden checks rerun on the filtered diff with the cached second-model tests. Policies: `public_api`
(`reviewer.keep_public_api`), `framework` (`reviewer.framework_callbacks`), `final` (both).

- **Run:** `python scripts/experiments/v1/exp_public_api_policy.py --policy public_api|framework|final --run`
- **Code version:** first public-API re-score (17 repositories) at main f2d0bce (after PR #52),
  2026-10-29; the `--policy` option and the 20-repository re-scores on the PR #64 branch
  (merged as ff98c90), 2026-10-29/30.
- **Inputs:** the AIDev rows of `main_results.csv` (3 methods × 20 repositories), the AIDev
  reports, the clones at their head sha and the second-model tests cached in the clone that ran
  each sweep. Docker for `--run`.
- **Outputs:** `results/raw/aidev_public_api/`, `aidev_framework_rule/`, `aidev_final_policy/`;
  `aidev_public_api_policy.csv`, `aidev_framework_rule.csv`, `aidev_final_policy.csv`, each with `.md`.
- **Runtime:** 13 min for the first re-score; 16 min for shotgun's reruns under the three
  policies; 18 min for pytorch_connectomics' reruns. **Models:** none.

### Framework callbacks and shotgun UI check

shotgun is a Textual app. The callback count shows what the judge and the Guard did with methods
the framework calls by name; the UI check mounts every screen and widget headless and compares
snapshots before and after each diff, including the policy-filtered diffs.

- **Run** (after the policy re-scores):
  ```bash
  python scripts/experiments/v1/exp_shotgun_ui.py           # runs scripts/experiments/v1/shotgun_ui_harness.py in shotgun's container
  python scripts/experiments/v1/exp_framework_callbacks.py  # offline; reads shotgun_ui.csv for the UI columns
  ```
  PR #64 branch (merged as ff98c90), 2026-10-29.
- **Outputs:** `results/raw/shotgun_ui/<variant>.json`; `shotgun_ui.csv`, `framework_callbacks.csv`.
- **Runtime:** UI check 7 min in one container; callback count not recorded. **Models:** none.

### Dependency re-check

Applies advisory's final diff (it holds every dependency removal any method applied) in each AIDev
container, makes the removed packages unavailable and reruns the tests.

- **Run:** `python scripts/experiments/v1/exp_dependency_check.py`. A first pass at e7278fa (PR #61 branch) was
  replaced by the reported pass with the PR #62 fix (a5e3353, merged as a439dcd), 2026-10-30.
- **Inputs:** the AIDev reports (18 applied removals in 6 repositories) and their containers.
- **Outputs:** `aidev_dependency_check.csv`, one row per removed package.
- **Runtime:** 70 min, about 39 of them paused to limit load from a parallel sweep. **Models:** none.

### Self-sweep

CleanSweep on a `git archive` copy of its own repository, gatekeeper then advisory. The Reviewer
sees everything except fixtures, demo, results and data; the Guard runs the copy's offline tests.

- **Run:** `python scripts/experiments/v1/exp_self_sweep.py --ref main [--modes gatekeeper advisory]` at main
  a439dcd (after PR #62), 2026-10-30; then `python scripts/experiments/v1/exp_self_sweep.py --table --ref a439dcd`
  (PR #66) for the table, which also counts the format items today's detector flags on that copy.
- **Outputs:** `results/raw/self_sweep/<mode>.json`; `results/summary/v1/self_sweep.csv`.
- **Runtime:** gatekeeper 59 min (18 test runs, 12 LLM requests); advisory 52 min (19 test runs;
  one request timed out after 600 s and was not retried). **Models:** judge, repair and probes
  `qwen36-35b-a3b`.

### v2: case studies and LLM-reviewer acceptance

Real-project case studies of `cleansweep clean` (v2), and an independent LLM's review of what
they applied and suggested. The review is **LLM-reviewer acceptance (independent model,
blinded)**, not a human evaluation.

- **Run:** `python scripts/experiments/v2/exp_case_study.py TARGET --name NAME --mode safe|thorough
  --budget minutes=120` (AIDev targets run in their container); `python
  scripts/experiments/v2/exp_review_sheet.py NAME --safe RUN [--thorough RUN]` writes the review
  sheet; `python scripts/experiments/v2/exp_llm_review.py sheet NAME` fills in its LLM-reviewer
  columns, `... table` writes the summary, `... calibration` writes a 20-row sheet for a person
  and `... kappa` compares them; `... mining` estimates the precision of the mined removal
  requests the same way.
- **Reviewer:** `VOYAGER_MODEL_ALT` (not the agents' model). It sees the code, the proposed change
  and the facts (detector evidence, references, test and probe results), never the agents'
  verdict, reasons, lane or mode; rows are shuffled (seed 572); 3 votes per row (seeds 0, 1, 2,
  temperature 0.3, reasoning off), the majority decides.
- **Outputs:** `results/raw/case_studies/<name>/` (report, diff, review sheet, `llm_review.json`);
  `results/summary/v2/llm_review_acceptance.csv`, `results/summary/v2/mining_llm_precision.csv`.
- **Code version:** this repository and slop-guard at 39ba2e2 (#92) and 81da3ea (#93, slop-guard
  in thorough mode); Telegram-Snowball-Sampling, Skill_Seekers and shotgun at 1b2f899 (after #98
  and #99, which fixed the harmful edits found in their first runs at 2d234e9).
- **Runtime:** this repository 15 min (safe) and 26 min (thorough); slop-guard and Telegram 2–4
  min each; Skill_Seekers 42 and 33 min; shotgun 36 min. The LLM review took 98–149 requests per
  sheet. **Models:** agents `qwen36-35b-a3b`; reviewer `glm-5-3`.

### v2: Manager scenarios

Four small projects (`tests/fixtures/scenarios/`) built so that one Manager decision is right:
rollbacks, conflict, budget and no baseline (the right answers are written in the script). The
other agents run without an LLM, so every run reaches the same decision point.

- **Run:** `python scripts/experiments/v2/exp_manager_scenarios.py [--repeats 3] [--managers llm
  rules]`; `--table` rebuilds the table from the runs.
- **Code version:** main at 015a98f (#106). The first run, at 843e98f, stopped on a script bug
  after 18 runs; it is kept as `results/raw/manager_scenarios_first/` and not reported.
- **Outputs:** `results/raw/manager_scenarios/<scenario>/<manager>-r<k>/`,
  `results/summary/v2/manager_scenarios.csv`.
- **Runtime:** a few minutes for the 24 runs. **Model:** the LLM Manager uses
  `qwen36-35b-a3b` with a fresh reply cache per repeat.

### v2: agentic vs v1, and the ablations

- **Run:** `python scripts/experiments/v2/exp_eval.py --targets toy demo --repeats 3 --methods
  agentic agentic-rules agentic-single_agent ...`, or `--split data/splits/swebench_tier1.json`,
  `--split data/splits/swebench_tier2_v2subset.json` (20 Tier 2 patches: all 18 that PatchDiff
  shows differ, plus 2 drawn with seed 572), `--split data/splits/aidev_repos.json --repos ...`.
  Method labels (`scripts/experiments/v2/methods_v2.py`): `agentic`, `agentic-<ablation>`
  (no_research, broadcast, inline_artifacts, no_lessons, no_coverage, single_agent),
  `agentic-rules` (the rule-based Manager) and v1's methods. Each repeat has its own caches.
- **Targets:** toy repo and demo app ×3 with every method above and v1's gatekeeper and
  advisory; SWE-bench Tier 1 (10) and the Tier 2 subset (20) with `agentic`; six AIDev
  repositories with `agentic`, chosen from v1's results before the runs: skillport,
  Telegram-Snowball-Sampling and Skill_Seekers (where v1 changed hidden behavior),
  pytorch_connectomics and shotgun (where its probes and judge mattered) and imgviz (where it
  applied nothing).
- **Code version:** the answer keys and AIDev at c68fcdc; SWE-bench at 7237ccc, after #118 (the
  SWE-bench workspace now stores per-test results). The first SWE-bench runs at c68fcdc
  (`results/raw/v2_eval/tier1_first`, `tier2_first`: every baseline had 0 passing tests) and
  five Tier 1 reruns made before the fix reached the clone (`tier1_unfixed_rerun`) are kept and
  not reported.
- **Runtime:** answer keys 3 h 36 min (60 runs); AIDev 3 h 27 min; Tier 1 28 min; Tier 2 subset
  32 min. **Model:** `qwen36-35b-a3b`.
- **Outputs:** `<out>/<target>__<method>__r<k>.json` and `<out>/runs.csv` (hidden behavior
  changed, code lines removed, rollbacks by tests and by probes, LLM requests and tokens,
  minutes, test runs, agent steps, exhausted budgets, lessons, step-backs).
- **Tables:** `python scripts/experiments/v2/exp_collect_v2.py` gathers the reports under
  `results/raw/v2_eval/{toy_demo,tier1,tier2,aidev}/` into `results/summary/v2/eval_runs.csv`.
  On SWE-bench and AIDev it adds v1's gatekeeper run on each target, the report
  `main_results.csv` counts, measured from its report the same way (code lines removed: lines
  removed from Python files that are not tests); its hidden result is v1's. Hidden changes are
  marked flaky as in v1 (another run made the same diff and its hidden checks did not change).
  `python scripts/experiments/v2/exp_tables_v2.py` then writes `eval_table` (mean and 95%
  bootstrap CI per target set and method; the team's verdicts; planted items found on the
  answer keys), `eval_paired` (the team against v1's gatekeeper on the same targets and repeats:
  McNemar on hidden changes, Wilcoxon on code lines removed) and `ablations` (quality, safety
  and cost per ablation on the answer keys and the injected set).

### v2: probe strength (PatchDiff recall, mutation score)

- **Run:** `python scripts/experiments/v2/exp_probe_strength.py --local tests/fixtures/toy_repo
  .cleansweep/demo/shop_app --tier data/splits/swebench_tier1.json --tier
  data/splits/swebench_tier2_v2subset.json [--resume]`.
- v1's guard-strength experiment with one change: after v1's compile and test checks, the
  coverage-guided probes the v2 Validator runs check what they miss. Same mutants (seed and
  limits) as v1, so the two compare mutant by mutant. No false-alarm run: v2's probes only
  probe changed code.
- **Compare:** `python scripts/experiments/v2/exp_probe_strength.py --compare` matches each
  record with v1's in `results/raw/guard_strength/` (same target, unit, mutant operator and
  line, or the same PatchDiff patch) and counts, per target set, the items both catch, only one catches
  and neither catches.
- **Outputs:** `results/raw/probe_strength/` (v1's record format),
  `results/summary/v2/probe_strength.csv`, `results/summary/v2/probe_strength_vs_v1.csv`.
- **Code version:** main at f84d568. **Runtime:** 60 min. **Model:** `qwen36-35b-a3b`.

### v2: detection by category on AIDev

- **Run:** `python scripts/experiments/v2/exp_detection.py` (static: files are extracted and
  parsed, never run; about 2 minutes).
- On the commented commits v1's mining processed, the v2 line-level detectors run on the
  commented files and each line item counts for the innermost function or class around it.
  v2's Auditor flags v1's units plus these; both are scored against the units reviewers asked
  agents to remove (precision and recall, overall and per category). The Investigator's LLM
  verdicts are not part of it.
- **Output:** `results/summary/v2/detection.csv`.
- **Code version:** PR #112 branch (merged as c003ca0).

### v2: slop-injection benchmark

Known slop planted into the toy repo and AIDev repositories at fixed seeds, then each method
cleans the whole project; the score is what it removed of the planted slop and of the traps.

- **Run:** `python scripts/experiments/v2/exp_inject.py run [--repos toy owner/name ...]
  [--seeds 1] [--methods agentic cleansweep one_shot_llm]`, then `... table`. The ablations on
  the injected set: `--methods agentic-rules agentic-single_agent agentic-no_research
  agentic-broadcast agentic-inline_artifacts agentic-no_lessons agentic-no_coverage`.
- **Plants** (in three package modules chosen by the seed): a leftover file, a dead function, an
  exact duplicate (both copies used), an unused import, a debug print (`f"{value=}"`), a
  commented-out block and an unused dependency; traps: a near-duplicate (half-even vs half-up
  rounding) and a framework callback (`ast.NodeVisitor.visit_Name`). A hidden test, kept outside
  the project, checks the planted code's behavior before and after the method's final diff.
- **Plant checks** (`prepare`, before every run): each plant must be a right answer: a leftover
  file nothing else names, a dead function with no caller, two copies that are really equal, an
  unused import the module does not use, a debug print and a commented-out block planted once, a
  dependency nothing in the project imports; the traps must really differ (the rounding helpers
  give different results, and removing `visit_Name` changes the count). An invalid plant is
  dropped and listed in the key (`dropped`). The hidden test must then pass on the injected
  project before any cleanup; if it fails, the modules are drawn again (at most 3 draws, the
  failures go to `rejected.txt`). `python scripts/experiments/v2/exp_inject.py validate` reruns
  the checks on the keys already prepared, with each report's hidden baseline.
- **One-shot scope:** `one_shot_llm` is shown the files the plants commit added or changed
  (`planted_files`), since the injected clones have no lines from agent pull requests.
- **Targets:** AIDev repositories become injected clones (`data/raw/aidev/injected/`, their head
  plus one commit with the plants) and run only in their containers; the toy repo is a local copy.
  `REPOS` in the script lists the toy repo and 9 AIDev repositories; `EXCLUDED` lists the ones
  left out with the reason: imgviz (replaced on request: its hidden test failed before any
  cleanup; its planted dependency was valid), openwebui-extensions (its hidden test failed on the
  injected baseline in all 3 draws), skillport and chatlas (fewer than three importable modules
  to plant in). mcp-nixos replaced imgviz and haliax replaced openwebui-extensions.
- **Seeds:** seed 1 with every method; seed 2 with every method; seed 3 with the team, no research
  squad and the single agent (run only if seed 2 ended by 2026-11-07). Seed 1 was rerun where
  the plants changed (mcp-nixos, every method) and for one-shot everywhere (its new scope).
- **Outputs:** `results/raw/inject/<repo>-s<seed>/` (key, hidden test, one report per method with
  its score); `results/summary/v2/injection.csv` (one row per plant, method and seed) and
  `injection_summary.csv` (recall, precision against the traps, traps removed, hidden behavior
  changed, per method and category); `injection_seeds` (each method per seed and pooled, with a
  95% bootstrap CI over project and seed) and `injection_paired` (the team against no research
  squad, the single agent, v1 and one-shot, paired by project and seed: Wilcoxon on planted
  items removed, exact McNemar on hidden changes). `exp_tables_v2.py` rebuilds the last three
  from `injection.csv`.
- **Code version:** seed 1 at main f84d568; the plant checks, the seed-1 reruns and seeds 2 and 3
  at 106c952 (#128), in the frozen clone `../cleansweep-runs-v2c`. **Runtime:** the team, v1 and
  one-shot on seed 1 took 8 h 25 min, partly beside the answer-key and AIDev runs (v1 alone took
  138 min on CORAL); the ablations took 9 h 54 min for their 70 runs (CORAL about an hour each).
  Seeds 2 and 3 and the reruns ran 2026-11-02 to 11-04, two or three sweeps at a time. Three
  laptop sleeps spoiled runs whose wall clock ran through them; each was rerun, and the spoiled
  ones are kept in `results/raw/inject_superseded/sleep_*` and not reported. **Model:**
  `qwen36-35b-a3b`.

### v2: real-project ablation

The test of whether investigation helps on real projects: the team, the team without its
research squad, and a single agent clean the five case-study projects.

- **Run:** `python scripts/experiments/v2/exp_case_study.py TARGET --name <project>-abl-<method>
  --budget minutes=120 [--ablation no_research|single_agent]` in safe mode (Skill_Seekers with
  `llm=300`, as in its case study), the AIDev targets in their containers, this repository on a
  scratch clone with the case study's excludes. Then `python
  scripts/experiments/v2/exp_real_ablation.py review` (a review sheet of each run's kept changes
  and the LLM reviewer's 3 votes on each, as in the case studies; LLM-judged), `... ui`
  (shotgun's UI check on each shotgun run's final diff, in its container, so the single agent,
  which has no UI check of its own, gets the same one), `... collect` and `... table`.
- **Targets:** this repository, slop-guard @ 7ef2113, Telegram-Snowball-Sampling @ 1787fe5,
  shotgun @ 4d344d5, Skill_Seekers @ 5b5d8df (the case studies' commits).
- **Counts:** lines removed (deleted minus added) and files deleted come from each run's final
  diff, so the three methods are counted the same way; the reviewer sees kept changes only; the
  wrong and debatable edits are the diff audit's checked verdicts on the run's kept code edits.
- **Caveat:** the single agent's 120 minutes start after its test baseline (`solo.py`), the
  team's at the start of the run; on shotgun the baseline took 14 minutes.
- **Outputs:** `results/raw/case_studies/<project>-abl-<method>/` (report, summary, review sheet,
  `llm_review.json`, `ui_check.json`); `results/summary/v2/real_ablation_runs.csv` (one row per
  run), `real_ablation.{csv,md}` (per method) and `real_ablation_tests.csv` (each method's wrong
  share of kept code edits against the team's, Fisher's exact test, two-sided, in both tiers;
  `reproduce_tables.sh` rebuilds both).
- **Code version:** 106c952 (#128), frozen clone `../cleansweep-runs-v2c`. **Runtime:** 15 runs,
  1.4 to 144 minutes each. **Models:** agents `qwen36-35b-a3b`; reviewer `glm-5-3`.

The same chain reran pytorch_connectomics with the team after #124 (a debugger call behind a
condition is only suggested): `exp_eval.py --split data/splits/aidev_repos.json --repos
PytorchConnectomics/pytorch_connectomics --methods agentic --out
results/raw/v2_eval/aidev_after124`.

### v2: adaptive investigation

The team with `core.agents.investigate: adaptive` (#145): only the candidates the rules call
uncertain go to an Investigator; the rules decide the rest.

- **Run:** chain I in the frozen clone `../cleansweep-runs-v2d` (1b98820), in two parts side by side:
  - the five real projects with `exp_case_study.py ... --investigate adaptive`, the same targets and budgets as the real-project ablation, written as `<project>-abl-adaptive`;
  - `exp_inject.py run --seeds 1 --methods agentic-adaptive` on the seed-1 keys the other methods used (copied into the clone, byte-identical).
- **Analysis:** the same as the real-project ablation. That is `exp_real_ablation.py review`, shotgun's UI check on that run, `collect` and `table`; the diff audit's run; then `exp_tables_v2.py` and `exp_rule_rescore.py run|table`. `exp_diff_audit.case_method` labels the runs `agentic-adaptive` from their summaries (#149).
- **Runtime:** 2026-11-04 15:03–17:56. The real projects took 4.3 to 66.3 minutes each; the injected projects took 2.5 to 62.3 minutes (CORAL). The laptop ran on battery from 15:03 until it was plugged in between 17:27 (59%, discharging) and 17:46 (on AC), with no sleep (`pmset -g log`). **Model:** `qwen36-35b-a3b`.

### v2: diff audit

An independent model reads every kept code edit and says whether it changes behavior anyone
could observe; every "yes" or "unsure" is then checked and the verdict recorded with its
evidence. The auditor's votes are LLM-judged, and so are the checks done by reading.

- **Run,** each pass after new runs land (all from the repository):
  1. `python scripts/experiments/v2/exp_diff_audit.py run` (resumable; a light job). Beside
     injected runs in a frozen clone, `scripts/experiments/v2/audit_loop.sh <clone>
     [<audit clone>]` does this every hour, after copying each finished injected project
     folder into `results/raw/inject/`.
  2. `... auto` (the flags two rules settle).
  3. `... match > matched.jsonl` (flags that make the same change as a checked edit carry its
     check; the rest are listed on stderr), and `... show EDIT ...` to read the rest.
  4. `... record --input FILE` for the matched and the hand-read checks (JSON lines: edit,
     verdict, evidence, and kind unless fine).
  5. A test folder for every new wrong verdict, run with `scripts/experiments/v2/confirm_batch.sh
     EDIT ...` (`exp_audit_confirm.py run`, detached), then `exp_audit_confirm.py record`. For a
     removed dependency that a test extra still installs, `exp_audit_confirm.py fresh
     EDIT=PACKAGE` says whether a plain install keeps it.
  6. `exp_diff_audit.py table`.

  Replayed from the repository on the same inputs, the pass of 2026-11-04 03:40 gives
  byte-identical `diff_audit_checks.csv`, `diff_audit.csv` and `diff_audit_types.csv`.
- **Scope:** the kept edits with a diff (not formatting) of the answer-key, SWE-bench and AIDev
  runs (with v1's gatekeeper run on each SWE-bench and AIDev target the team ran; on AIDev the
  original pytorch_connectomics row and the rerun after #124), every injected run of every seed,
  the case-study runs the results report and the real-project ablation. Identical edits (same
  project, file and diff) are merged.
- **Auditor:** `VOYAGER_MODEL_ALT`, never the agents' model. It sees the project, the file, the
  code around the edit at the run's starting commit, the diff, and where the removed names
  appear elsewhere in the project; never the method, the category, or the agents' evidence and
  verdicts. 3 votes (seeds 0, 1, 2, temperature 0.3, reasoning off); the majority decides.
- **Checks:** `rule: injection key` (an injected edit that removes only planted lines: fine for
  planted slop, wrong for a trap), `rule: agent patch` (deleting a file the SWE-bench agent's
  patch created), `reading (LLM-judged)` (the code around the edit and every use of the removed
  names), `targeted test` (a short test run on the code before and after the edit), `UI check`
  (shotgun).
- **Rubric,** applied the same way to every method (the method is never part of a check):
  - *wrong:* the edit changes behavior that something in the project or its users can actually
    trigger: a caller in the project (direct, by a string, through a decorator registration, or
    a framework callback the project's own entry points trigger, such as a web handler's
    `do_GET`, a Textual `compose`, a pydantic validator or a hatch build hook); the project's
    tests, scripts or examples; a command, option or page users reach through the documented
    interface, or a call the docs or the project's own messages tell users to make; a dependency
    something imports after a fresh install; a message users depend on (documented, or the only
    report of a failure or of where to go); and every removed trap of the injected set.
  - *debatable:* the edit removes code reachable only from outside the project (a public name
    nothing in the project calls or documents; a handler or stub a framework or grader might
    call but nothing in the project triggers, such as a placeholder whose only method raises
    `NotImplementedError`), or its intent is unclear (a progress or debug message, a pin or
    floor that only changes what a fresh install resolves). Reported apart, never as wrong.
  - *fine:* no observable change (unused private code, an import of a module without side
    effects, a dependency nothing imports, planted slop).
- **Tiers:** every verdict says how it was confirmed: *confirmed* (a targeted test, the UI check,
  or the injection key's or agent patch's rule) or *reading* (LLM-judged). Every safety claim
  names its tier.
- **Targeted tests** (`exp_audit_confirm.py`): every wrong verdict of every method gets a short
  test of the behavior it says the edit changes, not a sample. Tests live in
  `results/raw/diff_audit/tests/<edit>/`. Each runs in the run's own environment (the project's
  container, installed as the run installed it, for AIDev targets; a local copy for this
  repository and the fixtures) on the project as the run found it, then again with the edit
  applied. When the edit applies only after the run's earlier kept edits to the same file, those
  come first. A removed dependency is hidden as the Guard hides it, so only when no other
  installed package requires it. A test that passes before and fails after confirms the
  verdict. Otherwise the verdict stays reading, and `no_test.txt` says why no test could be
  written (for example, the code needs a package the project does not install). A test also
  runs on every check that cites its edit as the same change, so each copy is confirmed on its
  own. A "targeted test" recorded before this script, outside the run's environment, counts
  only once it is confirmed here. Results: `results/raw/diff_audit/tests/results.json`.
- **Kinds** of wrong and debatable edits: dynamic handler or stub (code reached by name at run
  time: a framework callback, a validator registered by decorator, a class registered by a
  string, a build hook, a seed or stub a grader loads), public name (reached by a direct
  reference, or by nothing), changed logic (the code stays but computes something else: a merge
  of near-duplicates that differ, a rewritten condition, an import of another function), deleted
  file (a script, example or data file something runs or loads), dependency, other (messages, a
  debugger call).
- **Rubric re-applied (2026-11-03):** the rubric above was written down after the first 335
  checks and every earlier verdict was read against it. The changes (edit, old verdict, new
  verdict, reason) are in `diff_audit_rubric_changes.csv`. `exp_audit_rubric.py` rebuilds that
  step from the committed 335 checks (`git show 6d5fefc:results/summary/v2/diff_audit_checks.csv`):
  its output equals the checks and changes committed in 11ca94b, byte for byte.
- **Calibration:** `... sheet` writes 20 checks drawn at random (seed 572) as the auditor saw
  them, blinded, with an empty verdict column (by default `.notes/report/
  audit_calibration_sheet.md`, kept local); once a person fills it in, `... kappa` gives Cohen's
  kappa against the recorded verdicts. Until then the readings are not checked by a human.
- **Outputs:** `results/raw/diff_audit/audit.json` (every vote); `diff_audit_checks.csv` (edit,
  verdict, evidence, checked_by, kind); `diff_audit.csv` (per method and target set: kept code
  edits, the auditor's yes / unsure / no, wrong edits in all tiers, confirmed and by reading,
  debatable and fine edits, the wrong rate of all tiers and of the confirmed tier with 95%
  bootstrap CIs over runs, and how many wrong edits every check missed);
  `diff_audit_types.csv` (the wrong and debatable edits of each method by kind).
- **Code version:** the audit from #129 with the fixes of #132 and #133. **Model:** `glm-5-3`.

### v2: the extended framework rule, re-scored

The diff audit found that removed dynamically called methods were most of the team's wrong edits
on the injected set, so the framework-callback rule now also covers the standard library's
`http.server` handlers and `ast.NodeVisitor`, PyTorch and Lightning modules and hatchling build
hooks (#139). The finished runs were made without it; this measures what it would have changed.

- **Run:** `python scripts/experiments/v2/exp_rule_rescore.py moved` (no Docker), `... run`,
  `... table`.
- **Method:** for every injected run of a method that plans with `build_plan` (v1, the team and
  its ablations, the single agent; not the one-shot baseline), the kept dead-code and duplicate
  edits on methods the rule now marks as framework callbacks, with the code graph of the run's
  starting commit. Those edits would have gone to the suggest lane. For a run where the rule
  moves any, the run's other kept edits are applied in order to the starting commit, the plants
  are scored and the hidden test runs on that diff in a fresh workspace, as `exp_inject.py`
  does; the diff audit's verdicts carry over to the edits that stay.
- **Outputs:** `results/raw/inject_rule/<project>-s<seed>/<method>.json`;
  `results/summary/v2/inject_rule.csv` (per method, as run and with the rule: edits moved,
  planted slop removed, traps removed, hidden tests changed, wrong edits in all tiers and
  confirmed). The numbers as run stay the reported ones; "with rule" is shown next to them.
- **Code version:** #139's rule and #140's script, run from the results branch at 3fda062
  (resumed at 6859ed7) on all 210 injected runs of seeds 1–3, Docker. The rule moves edits in 38
  of them. **Runtime:** 26 minutes.

### v2: watch mode

- **Run:** `python scripts/experiments/v2/exp_watch.py demo [--no-llm]` and
  `python scripts/experiments/v2/exp_watch.py simulate`.
- **demo:** prepares the demo app as a git repository, polls it, commits `demo/feature.patch`
  and polls again; each poll records its decision and reason, and a "clean" runs `clean` on a
  copy of the commit. **simulate:** replays the 20 kept AIDev histories (the 300 commits and
  cached slop measurements of v1's Scheduler replay) under the watch rule, with no test budget
  and with the test runs v1's adaptive policy spent, beside v1's policies.
- **Outputs:** `results/raw/watch_demo/`, `results/summary/v2/watch_replay.csv`.
- **Code version:** PR #103 branch (merged as 12caf01). Static: no LLM, no Docker.

## Getting the data

Everything under `data/` except `data/splits/` is gitignored. In order:

1. **PatchDiff.** `python scripts/data/data_fetch_patchdiff.py` clones PatchDiff at the commit pinned
   in `configs/data.yaml` (it holds the three agents' SWE-bench patches), downloads the paper's
   results archive from Zenodo (record 17074796), checks its sha256, extracts it and writes the
   label and hidden-test index.
2. **SWE-bench Verified** (`SWE-bench/SWE-bench_Verified` on Hugging Face, test split) downloads
   the first time a script loads it, e.g. `python scripts/data/data_summary.py`. The tier splits are
   committed; `python scripts/data/data_make_splits.py` rewrites them from the index and this cache.
3. **AIDev tables.** The four AIDev-pop tables of the `hao-li/AIDev` dataset; we used revision
   `b8dc67df93e7c11f6f20c84129db7232eb1ec253`:
   ```bash
   huggingface-cli download hao-li/AIDev repository.parquet pull_request.parquet \
       pr_review_comments.parquet pr_commits.parquet --repo-type dataset \
       --revision b8dc67df93e7c11f6f20c84129db7232eb1ec253 --local-dir data/raw/aidev
   ```
4. **AIDev repositories.** `python scripts/data/data_aidev_select.py` sampled 120 candidates (seed 0),
   cloned them and tested each in Docker (about 2 h). Its results are committed
   (`data/splits/aidev_repos.json`, `results/data_summary/aidev_filter.csv`), and a rerun skips
   candidates already in the CSV. To get only the clones the sweeps need, make a blobless clone
   (`git clone --filter=blob:none <clone_url>`, git LFS filters off) of each repository in
   `aidev_repos.json` at `data/raw/aidev/repos/<owner>__<name>`, and check that it still contains
   the recorded `head_sha`.
5. **AIDev histories.** `python scripts/experiments/v1/exp_replay.py` caches each repository's last 300
   first-parent commits. Then `python scripts/data/data_aidev_scope.py --extend commaai/opendbc
   PytorchConnectomics/pytorch_connectomics` caches the longer scope histories of the two
   repositories with no agent commit in that window and writes `aidev_scope.csv`.
6. **Mining and labels**, only for the ranker and detection experiments (commands above).
   `labels` adds treeless clones of the commented repositories to `data/raw/aidev/repos/`.

| Path | Contents | Written by | Size |
|---|---|---|---|
| `data/raw/swebench_verified.parquet` | SWE-bench Verified test split (500 tasks) | first load | 2 MB |
| `data/raw/patchdiff/`, `patchdiff_zenodo/` | PatchDiff repository, results archive | `data_fetch_patchdiff.py` | 0.7 GB |
| `data/processed/patchdiff_index.json`, `patchdiff_tests/` | labels, hidden tests per patch | `data_fetch_patchdiff.py` | 14 MB |
| `data/raw/aidev/*.parquet` | AIDev-pop tables | download | 1 GB |
| `data/raw/aidev/repos/` | repository clones | step 4 and `labels` | 15 GB (about 200 clones) |
| `data/processed/aidev_history/`, `aidev_scope_history/`, `aidev_slop/` | histories, slop cache | `exp_replay.py`, `data_aidev_scope.py` | 15 MB |
| `data/processed/aidev_{requests,labels,detection}.parquet` | mining and labels | `data_aidev_mine.py` | 1 MB |
| `data/splits/` | SWE-bench tiers, AIDev repositories (committed) | `data_make_splits.py`, `data_aidev_select.py` | small |

## Requirements

- **Python 3.11** (the runs used 3.11.16):
  ```bash
  python3.11 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt && pip install -e .
  pytest -q -m "not llm and not docker and not network and not slow"   # offline tests
  ```
- **Docker** (the runs used 29.8.0). Nothing is built from this repository; images are pulled.
  - SWE-bench: the prebuilt per-instance images named in the dataset rows
    (`swebench/sweb.eval.x86_64.<instance>:latest`), run as `linux/amd64`, emulated on arm64: a
    3.8 GB pull took about 2 min and one test run 4–13 s. Tier 1's 4 images take about 13 GB,
    Tier 2's 21 images about 44 GB (3.8–10.6 GB each, shared layers counted once).
  - AIDev: `python:3.11` (1.6 GB). Each run installs the repository in a fresh container with
    network access, then disconnects the network before any project code runs.
  - Containers are removed when a run ends; after a killed run, remove its container by hand.
- **LLM endpoint:** any OpenAI-compatible endpoint, set in a `.env` file at the repository root
  (never committed): `VOYAGER_API_KEY`, `VOYAGER_BASE_URL`, `VOYAGER_MODEL` (judge, repair,
  probes, one-shot, mining) and `VOYAGER_MODEL_ALT` (AIDev hidden tests).
  `python scripts/tools/voyager_ping.py` checks the connection. Without a key, sweeps run offline
  (detectors and tests; no judge, repair or probe requests). Probe, one-shot and mining requests
  turn reasoning off with a provider option (`core.guard.probe_extra_body`,
  `exp.one_shot_extra_body`); adjust it for another provider. Requests time out after 600 s.
- **Caches:** LLM replies in `.cleansweep/llm_cache.sqlite`, probes in `.cleansweep/probes/`, AIDev
  hidden tests in `.cleansweep/hidden_tests/`. With them a rerun makes no new requests and faces
  the same hidden tests.
- **Reference machine:** an arm64 laptop, 12 CPUs, 18 GB memory; Docker VM with 12 CPUs, 7.7 GB.
- **Budget:** about 65 GB of disk for all images and data (13 GB of images for Tier 1 alone). Time
  is dominated by the Tier 2 grid (about 28 h) and the AIDev sweeps (about two days with two jobs);
  each other experiment took between a few minutes and about 4 h.

## Re-running a sweep on a frozen commit

Long sweeps ran in a separate clone frozen at a recorded commit, so the main checkout could move
on meanwhile:

1. Clone the repository and check out the recorded sha, e.g.
   `git clone <repository URL> cleansweep-run && git -C cleansweep-run checkout --detach 07a4dad`.
2. In the clone, link `data/raw` and `data/processed` to the main checkout's folders, and link or
   copy `.env`. Both data folders are needed: without `data/processed` an AIDev sweep has no agent
   scope and silently reviews the whole repository. We discarded runs made that way; the runner
   now refuses AIDev targets without a cached history.
3. To reuse replies, copy `.cleansweep/probes/` and `.cleansweep/hidden_tests/`, and back up the
   LLM cache with `sqlite3 <cache> ".backup <copy>"` (safe while another job writes to it). Link
   any report folder the script reads, e.g. the Tier 1 reports for `exp_guard_on_oneshot.py`.
4. Start the job detached, in its own process group, with the clone's code on the path (we shared
   one virtual environment across clones; on a laptop, keep the machine awake):
   ```bash
   set -m
   nohup env PYTHONPATH="$PWD/src" python scripts/experiments/v1/exp_swebench.py \
       --tier data/splits/swebench_tier2.json --out results/raw/swebench_t2 > job.out 2>&1 &
   disown
   ```
5. Run at most two sweeps at once (four at once doubled test times on the largest repository).
   Failed runs are logged in `<out>/errors/`; restart with the same command plus `--resume`. To
   stop a job, send SIGTERM to its process group, then remove its container.
6. Copy the reports back to `results/raw/`, or pass the clone's folders to the scripts that read
   them: `exp_collect.py` (`--t1`, `--t2`, `--t2-oneshot`, `--t2-rerun`, `--aidev`, `--aidev-rerun`,
   `--oneshot-retry`), `exp_oneshot_breakages.py` (`--t2`, `--t2-oneshot`, `--t2-rerun`),
   `exp_oneshot_compile.py` and `exp_guard_on_oneshot.py` (`--t2-oneshot`; the first also `--runs`),
   `exp_aidev_summary.py`, `exp_public_api_policy.py` and `exp_dependency_check.py` (`--runs`), and
   `exp_framework_callbacks.py` and `exp_shotgun_ui.py` (`--reports`). Without a flag they read the
   reported runs from `../cleansweep-archive/raw/<clone>/results_raw/`.

Current main does not reproduce the as-run numbers: since v1.0 the Reviewer keeps public API and
framework callbacks in the suggest lane, format edits follow the project's ruff settings (#63),
and `reviewer.exclude` also covers the over-engineering review (#66). Use the recorded sha to
repeat a reported run.

## Regenerating the tables

```bash
bash scripts/reproduce_tables.sh          # results/summary/ and results/figures/
bash scripts/reproduce_tables.sh DIR      # or DIR/summary/ and DIR/figures/
```

This rebuilds the aggregate tables and figures offline (no Docker, LLM or raw reports) from the
committed per-run CSVs. `exp_tables.py` builds `main_table`, `paired_tests`, `ablation`,
`oneshot_series` and the main figures from `main_results.csv` and `guard_strength.csv`;
`exp_scheduler_tradeoff.py` builds `scheduler_tradeoff.csv` and its figure from
`scheduler_replay.csv`; `exp_tables_v2.py` builds v2's `eval_table`, `eval_paired`,
`ablations`, `injection_summary`, `injection_summary_seeds12` (seeds 1 and 2, which every method
ran), `injection_seeds` and `injection_paired` from `results/summary/v2/eval_runs.csv` and
`injection.csv`; `exp_real_ablation.py table` builds `real_ablation` and `real_ablation_tests`
(Fisher's exact test of each method's wrong edits against the team's) from
`real_ablation_runs.csv`. On a clean checkout, `git status results/` shows no change afterwards.
`tests/scripts/test_reproduce_tables.py` runs it on a small fixture (`tests/fixtures/results_small/`)
and checks that every table comes out byte for byte. Set `PYTHON` to pick the interpreter.

The per-run CSVs need the raw reports, clones, Docker or the LLM, so the script leaves them
alone:

| Committed file in `results/summary/` | Written by | Needs |
|---|---|---|
| `v1/main_results.csv` | `exp_collect.py` | every sweep report folder |
| `v1/aidev_sweeps.csv`, `.md` | `exp_aidev_summary.py` | AIDev reports, cached hidden tests |
| `v1/guard_strength.csv` | `exp_guard_strength.py` | `results/raw/guard_strength/` (Docker, probe requests) |
| `v1/guard_on_oneshot.csv`, `.md` | `exp_guard_on_oneshot.py` | SWE-bench reports, Docker, probe requests |
| `v1/oneshot_breakages.csv`, `.md` | `exp_oneshot_breakages.py` | SWE-bench reports, Docker |
| `v1/oneshot_compile.csv` | `exp_oneshot_compile.py` | `guard_on_oneshot.csv`, AIDev reports and clones |
| `v1/aidev_public_api_policy.csv`, `v1/aidev_framework_rule.csv`, `v1/aidev_final_policy.csv`, `.md` | `exp_public_api_policy.py --policy ...` | AIDev reports and clones, Docker for `--run` |
| `v1/aidev_dependency_check.csv` | `exp_dependency_check.py` | AIDev reports, Docker |
| `v1/shotgun_ui.csv` | `exp_shotgun_ui.py` | shotgun reports, policy diffs, Docker |
| `v1/framework_callbacks.csv` | `exp_framework_callbacks.py` | shotgun reports, `shotgun_ui.csv` |
| `v1/scheduler_replay.csv`, `v1/scheduler_curves.csv` | `exp_replay.py` | AIDev clones and histories |
| `v1/ranker_cv.csv`, `v1/ranker_status.json` | `exp_train_ranker.py` | `data/processed/aidev_labels.parquet` |
| `v1/ranker_report.md` | `exp_ranker_report.py` | `data/processed/aidev_labels.parquet` |
| `v1/reviewer_detection.csv` | `exp_reviewer_detection.py` | labels and detection parquet files |
| `v1/self_sweep.csv` | `exp_self_sweep.py --table` | `results/raw/self_sweep/` reports |
| `v2/eval_runs.csv` | `exp_collect_v2.py` | `results/raw/v2_eval/` reports, v1's archived reports |
| `v2/injection.csv` | `exp_inject.py table` | `results/raw/inject/` reports |
| `v2/real_ablation_runs.csv` | `exp_real_ablation.py collect` | the ablation records, `llm_review.json`, `ui_check.json`, `diff_audit_checks.csv` |
| `v2/diff_audit.csv`, `v2/diff_audit_types.csv` | `exp_diff_audit.py table` | the raw reports, `results/raw/diff_audit/audit.json`, `diff_audit_checks.csv` |
| `v2/diff_audit_checks.csv` | `exp_diff_audit.py auto`, `match` and `record` (hand-read checks as JSON lines), `exp_audit_confirm.py record` | the flagged edits, targeted tests |
| `v2/diff_audit_rubric_changes.csv` | by hand, once | `diff_audit_checks.csv` before the rubric was written down |
| `v2/inject_rule.csv` | `exp_rule_rescore.py table` | `results/raw/inject_rule/`, the injected reports, `diff_audit_checks.csv` |
| `v2/probe_strength.csv`, `v2/probe_strength_vs_v1.csv` | `exp_probe_strength.py` (`--compare`) | `results/raw/probe_strength/` (Docker, probe requests), `results/raw/guard_strength/` |
| `v2/manager_scenarios.csv` | `exp_manager_scenarios.py` | the LLM |
| `v2/llm_review_acceptance.csv`, `v2/mining_llm_precision.csv` | `exp_llm_review.py` | case-study review sheets, the reviewer model |
| `v2/detection.csv` | `exp_detection.py` | AIDev clones, mined labels |
| `v2/watch_replay.csv` | `exp_watch.py simulate` | AIDev histories, cached measurements |

The files in `results/data_summary/` come from the data scripts: `data_summary.py`
(`swebench_patchdiff.csv`, `tiers.csv`, `aidev_funnel.csv`), `data_aidev_select.py`
(`aidev_filter.csv`), `data_aidev_mine.py` (`aidev_taxonomy.csv`, `aidev_rules.csv`),
`data_detection_by_category.py` and `data_aidev_scope.py`.
