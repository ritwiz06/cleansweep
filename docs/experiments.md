# Experiments

This page lists the experiments behind the CleanSweep results: how to run each one, which code
version produced the reported numbers, what it reads and writes, how long it took and which LLMs
it used. The pipeline is described in [architecture.md](architecture.md); the results are in the
README and in `results/summary/v1/`.

- **Code version** is the commit the reported runs used. Long runs ran in a separate clone frozen
  at that commit ("main at 07a4dad"); runs made from a working branch name its pull request.
  "Not recorded" means our run log does not say.
- Per-run reports go to `results/raw/<folder>/` (gitignored). Files in `results/summary/v1/`,
  `results/data_summary/` and `results/figures/v1/` are committed.
- The frozen clones are gone; their reports and caches are kept outside the repository in
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
| [Answer keys](#answer-keys-toy-repo-and-demo-app) | `app.live_runner` | main, 2026-10-26/27 (not recorded) | `main_results.csv` |
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
  python -m app.live_runner --target tests/fixtures/toy_repo --method cleansweep \
      --judge-mode advisory --run-id 20261026_toy_advisory_probes
  ```
  Recorded on both targets: `cleansweep` (gatekeeper and advisory), `guard_tests_only`,
  `tools_only` on 2026-10-26; `one_shot_llm` on 2026-10-27. Commits not recorded.
- **Inputs:** `tests/fixtures/toy_repo` (13 planted items in `toy_repo_expected.json`, hidden
  tests in `toy_repo_hidden/`); `demo/shop_app` plus `demo/feature.patch` (7 planted items,
  hidden tests in `shop_app_hidden/`). The hidden tests are hand-written.
- **Outputs:** `results/raw/live/<run_id>/` (`events.jsonl`, `report.json`); the `toy` and `demo`
  rows of `main_results.csv`. Three demo recordings ship in `demo/replay/` with repo-relative
  paths, so the dashboard's Replay works on a fresh clone: the advisory run with the v1.0
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
bash scripts/reproduce_tables.sh          # results/summary/v1/ and results/figures/v1/
bash scripts/reproduce_tables.sh DIR      # or DIR/summary/ and DIR/figures/
```

This rebuilds the aggregate tables and figures offline (no Docker, LLM or raw reports) from the
committed per-run CSVs. `exp_tables.py` builds `main_table`, `paired_tests`, `ablation`,
`oneshot_series` and the main figures from `main_results.csv` and `guard_strength.csv`;
`exp_scheduler_tradeoff.py` builds `scheduler_tradeoff.csv` and its figure from
`scheduler_replay.csv`. On a clean checkout, `git status results/` shows no change afterwards.
`tests/scripts/test_reproduce_tables.py` runs it on a small fixture (`tests/fixtures/results_small/`)
and checks that every table comes out byte for byte. Set `PYTHON` to pick the interpreter.

The per-run CSVs need the raw reports, clones, Docker or the LLM, so the script leaves them
alone:

| Committed file in `results/summary/v1/` | Written by | Needs |
|---|---|---|
| `main_results.csv` | `exp_collect.py` | every sweep report folder |
| `aidev_sweeps.csv`, `.md` | `exp_aidev_summary.py` | AIDev reports, cached hidden tests |
| `guard_strength.csv` | `exp_guard_strength.py` | `results/raw/guard_strength/` (Docker, probe requests) |
| `guard_on_oneshot.csv`, `.md` | `exp_guard_on_oneshot.py` | SWE-bench reports, Docker, probe requests |
| `oneshot_breakages.csv`, `.md` | `exp_oneshot_breakages.py` | SWE-bench reports, Docker |
| `oneshot_compile.csv` | `exp_oneshot_compile.py` | `guard_on_oneshot.csv`, AIDev reports and clones |
| `aidev_public_api_policy.csv`, `aidev_framework_rule.csv`, `aidev_final_policy.csv`, `.md` | `exp_public_api_policy.py --policy ...` | AIDev reports and clones, Docker for `--run` |
| `aidev_dependency_check.csv` | `exp_dependency_check.py` | AIDev reports, Docker |
| `shotgun_ui.csv` | `exp_shotgun_ui.py` | shotgun reports, policy diffs, Docker |
| `framework_callbacks.csv` | `exp_framework_callbacks.py` | shotgun reports, `shotgun_ui.csv` |
| `scheduler_replay.csv`, `scheduler_curves.csv` | `exp_replay.py` | AIDev clones and histories |
| `ranker_cv.csv`, `ranker_status.json` | `exp_train_ranker.py` | `data/processed/aidev_labels.parquet` |
| `ranker_report.md` | `exp_ranker_report.py` | `data/processed/aidev_labels.parquet` |
| `reviewer_detection.csv` | `exp_reviewer_detection.py` | labels and detection parquet files |
| `self_sweep.csv` | `exp_self_sweep.py --table` | `results/raw/self_sweep/` reports |

The files in `results/data_summary/` come from the data scripts: `data_summary.py`
(`swebench_patchdiff.csv`, `tiers.csv`, `aidev_funnel.csv`), `data_aidev_select.py`
(`aidev_filter.csv`), `data_aidev_mine.py` (`aidev_taxonomy.csv`, `aidev_rules.csv`),
`data_detection_by_category.py` and `data_aidev_scope.py`.
