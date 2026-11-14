# Results

Every result in detail: what was run, the numbers, and where the files are.
[experiments.md](experiments.md) has the commands, code versions and runtimes;
`results/summary/v1/`, `results/summary/v2/` and `results/summary/v3/` have the CSVs. v1 (Phase 1)
comes first, then [v2: the agent team](#v2-the-agent-team) (Phase 2) and, at the end,
[v3: the evaluation](#v3-the-evaluation-phase-3-frozen-2026-11-13-1200) (Phase 3).

## Answer keys: toy repo and demo app

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

## SWE-bench Tier 1

Ten plausible agent patches from SWE-bench Verified (PatchDiff's three agents, 4 instances:
`pytest-dev__pytest-10081`, `django__django-11095`, `sympy__sympy-11618` × 3 agents, and
`pydata__xarray-3151` × 1; 3 of the 10 behave differently from the developer's fix). Each runs in
its prebuilt SWE-bench Docker image (emulated amd64 on an arm64 laptop). On these targets the
Reviewer looks only at what the agent's patch wrote (`reviewer.scope`), and so does the
tools-only baseline. Hidden checks run in a fresh container: the instance's FAIL_TO_PASS and
PASS_TO_PASS tests plus PatchDiff's generated tests for that patch (1 to 38 stable tests per
patch), which the Guard never sees. 2026-10-26, judge `qwen36-35b-a3b`,
`scripts/experiments/v1/exp_swebench.py --tier data/splits/swebench_tier1.json --out results/raw/swebench_t1`.

| Method | Items found | Edits applied | Files removed | Lines removed | Rolled back | Test runs | Hidden changed | Min per patch |
|---|---|---|---|---|---|---|---|---|
| `cleansweep`, gatekeeper | 20 leftover files | 20 | 20 | 570 | 0 | 48 | 0/10 | 2.2 |
| `cleansweep`, advisory (with probes) | 20 leftover files | 20 | 20 | 570 | 0 | 48 | 0/10 | 1.8 |
| `guard_tests_only` (advisory) | 20 leftover files | 20 | 20 | 570 | 0 | 48 | 0/10 | 1.8 |
| `tools_only` | vulture + ruff | 8 | 0 | 18 | n/a | 30 | 0/10 | 1.2 |
| `one_shot_llm` | 17 files the model changed | 17 | 10 | 302 | n/a | 30 | **3/10** | 2.3 |

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
- `one_shot_llm` (one request, the model returns whole files as JSON, nothing checked) deletes
  most scratch files too. It also rewrites `sympy/geometry/point.py` in all three sympy patches and
  changes their hidden behavior. Before S18 it asked for a diff, which never applied.
- Cost: 14 live LLM calls (about 23k prompt and 46k completion tokens) for the first method on each
  patch, plus 8 for the gatekeeper rerun after #26; the other methods were answered from the
  cache. The hidden checks add about 0.9 minutes
  per patch. Tables: `results/summary/v1/swebench_tier1*.md`.

## SWE-bench Tier 2

**57 PatchDiff patches × 5 methods** (`scripts/experiments/v1/exp_swebench.py --tier data/splits/swebench_tier2.json`
in a frozen clone of main, 2026-10-26 15:08 to 2026-10-27 21:39 with the reruns). Tier 2 has 60 patches, from 21
instances in 11 repositories. The three `psf__requests-2317` patches were left out: `requests`'
own tests call httpbin.org live, so two of them took 2.7 and 3.5 hours, and the third was stopped.

- **First run:** 53 patches finished completely.
- **Four patches failed there and were rerun with the fixes from #39**, in a second frozen clone at 83e3b00:
  - three OpenHands patches applied in the container only with `patch --fuzz`;
  - one LearnByInteract patch created CRLF files that the container sync couldn't delete.
  - Their rows come from that newer code (runner-mode probes, 3 stability runs for hidden tests).
- **The `one_shot_llm` rows are the rerun of the fixed baseline** (JSON files instead of a diff) in the second clone, for all 57 patches.

What happened:
- **CleanSweep, both judge modes, and `guard_tests_only`** applied the same edits on every patch: 78 edits and 2,130 lines in total, all of them leftover files the agent created (13 more items stayed in the suggest lane). There were 0 rollbacks, and hidden behavior changed on **0 of 57**.
  - One hidden change under `guard_tests_only` (`sympy-11618`/CodeStory) is marked flaky. The same two edits under both cleansweep modes changed nothing, so the PatchDiff test flipped, not the code.
- **`one_shot_llm`:**
  - It removes about as many lines as CleanSweep (30.1 vs. 37.4 per patch; Wilcoxon p = 0.70) with 0 invalid replies.
  - It **changes hidden behavior on 9 of 57 patches** (16%, 95% CI 7–26%; exact McNemar p = 0.0039 against gatekeeper).
  - The model rewrites the agent's changed source files, and nothing checks the result.
- **`tools_only`** removes 0.9 lines per patch (unused imports) and changes nothing hidden.
- **`one_shot_compile`** (the same diff, discarded when a rewritten file doesn't compile; no extra LLM call) changes hidden behavior on **2 of 57** (McNemar p = 0.5) and removes 27.8 lines per patch (Wilcoxon p = 0.087).
- **`one_shot_retry`** (the compile errors go back to the model once, and the second reply is applied) changes hidden behavior on **5 of 57** (p = 0.063) at 30.1 lines per patch. The second reply compiled for the 4 sympy and scikit-learn patches but not for the 3 sphinx ones, which end with the same stray `"` after the last line (1 new LLM request each; the first reply came from the cache). The 5 are those 3 and the 2 Django behavior changes that the compile check keeps too; no second reply that compiled changed hidden behavior.
- **Minutes per patch (median):** gatekeeper 2.2, advisory 1.3, `guard_tests_only` 1.4, `tools_only` 0.8, `one_shot_llm` 1.4. Medians, because one Django gatekeeper run took 197 minutes while the laptop slept (mean 8.2).

## Main table

Mean per target and 95% bootstrap CI (2,000 resamples). "Answer keys" pools the toy repo and the
demo app (one target each). Invalid output = one-shot replies that couldn't be applied: they are
left out of the means and counted apart (there were none). Flaky hidden = hidden changes that
another method's identical edits did not repeat; they are left out of the hidden-changed mean.
`scripts/experiments/v1/exp_collect.py` then `scripts/experiments/v1/exp_tables.py`; files in `results/summary/v1/`.

| target set | method | n | lines removed | edits | hidden changed | flaky hidden | test runs | minutes (median) |
|---|---|---|---|---|---|---|---|---|
| answer keys | cleansweep, gatekeeper | 2 | 48.5 [47.0, 50.0] | 7.5 [5.0, 10.0] | 0.00 [0.00, 0.00] | 0 | 4.5 | 0.1 |
| answer keys | cleansweep, advisory | 2 | 48.5 [47.0, 50.0] | 7.5 [5.0, 10.0] | 0.00 [0.00, 0.00] | 0 | 8.0 | 0.1 |
| answer keys | `guard_tests_only` | 2 | 57.5 [56.0, 59.0] | 8.5 [6.0, 11.0] | 1.00 [1.00, 1.00] | 0 | 4.5 | 0.1 |
| answer keys | `tools_only` | 2 | 50.5 [38.0, 63.0] | 9.0 [7.0, 11.0] | 1.00 [1.00, 1.00] | 0 | 0.0 | 0.0 |
| answer keys | `one_shot_llm` | 2 | 47.0 [47.0, 47.0] | 6.5 [5.0, 8.0] | 0.00 [0.00, 0.00] | 0 | 0.0 | 0.4 |
| SWE-bench Tier 1 | cleansweep, gatekeeper | 10 | 57.0 [13.3, 122.9] | 2.0 [0.6, 4.1] | 0.00 [0.00, 0.00] | 0 | 4.8 | 1.5 |
| SWE-bench Tier 1 | cleansweep, advisory | 10 | 57.0 [13.3, 122.9] | 2.0 [0.6, 4.1] | 0.00 [0.00, 0.00] | 0 | 4.8 | 1.1 |
| SWE-bench Tier 1 | `guard_tests_only` | 10 | 57.0 [13.3, 122.9] | 2.0 [0.6, 4.1] | 0.00 [0.00, 0.00] | 0 | 4.8 | 1.1 |
| SWE-bench Tier 1 | `tools_only` | 10 | 1.8 [0.0, 4.2] | 0.8 [0.4, 1.2] | 0.00 [0.00, 0.00] | 0 | 3.0 | 0.5 |
| SWE-bench Tier 1 | `one_shot_llm` | 10 | 30.2 [8.4, 62.3] | 1.7 [0.9, 2.4] | 0.30 [0.00, 0.60] | 0 | 3.0 | 2.4 |
| SWE-bench Tier 1 | `one_shot_compile` | 10 | 24.1 [2.9, 57.9] | 1.1 [0.4, 2.0] | 0.00 [0.00, 0.00] | 0 | 3.0 | 2.4 |
| SWE-bench Tier 1 | `one_shot_retry` | 10 | 30.3 [8.5, 62.4] | 1.6 [0.9, 2.3] | 0.00 [0.00, 0.00] | 0 | 3.0 | 2.5 |
| SWE-bench Tier 2 | cleansweep, gatekeeper | 57 | 37.4 [25.7, 53.5] | 1.4 [1.0, 1.9] | 0.00 [0.00, 0.00] | 0 | 4.8 | 2.2 |
| SWE-bench Tier 2 | cleansweep, advisory | 57 | 37.4 [25.7, 53.5] | 1.4 [1.0, 1.9] | 0.00 [0.00, 0.00] | 0 | 4.8 | 1.3 |
| SWE-bench Tier 2 | `guard_tests_only` | 57 | 37.4 [25.7, 53.5] | 1.4 [1.0, 1.9] | 0.00 [0.00, 0.00] | 1 | 4.8 | 1.4 |
| SWE-bench Tier 2 | `tools_only` | 57 | 0.9 [0.4, 1.6] | 0.9 [0.8, 1.1] | 0.00 [0.00, 0.00] | 0 | 3.0 | 0.8 |
| SWE-bench Tier 2 | `one_shot_llm` | 57 | 30.1 [21.0, 41.0] | 1.7 [1.4, 2.0] | **0.16 [0.07, 0.26]** | 0 | 3.0 | 1.4 |
| SWE-bench Tier 2 | `one_shot_compile` | 57 | 27.8 [19.0, 38.9] | 1.5 [1.1, 1.8] | 0.04 [0.00, 0.09] | 0 | 3.0 | 1.4 |
| SWE-bench Tier 2 | `one_shot_retry` | 57 | 30.1 [21.0, 41.0] | 1.6 [1.3, 2.0] | 0.09 [0.02, 0.18] | 0 | 3.0 | 1.5 |

`results/figures/v1/safety_vs_yield.png` plots lines removed against the hidden-change rate per
method, with 95% CIs.

**The one-shot series at stated yield** (`oneshot_series.md`; each variant against gatekeeper,
exact McNemar on hidden changes, Wilcoxon on lines removed):

| tier | variant | lines removed | hidden changed | McNemar p | Wilcoxon p |
|---|---|---|---|---|---|
| Tier 2 (57) | `one_shot_llm` | 30.1 [21.0, 41.0] | 9/57 | 0.0039 | 0.70 |
| Tier 2 (57) | `one_shot_compile` | 27.8 [19.0, 38.9] | 2/57 | 0.5 | 0.087 |
| Tier 2 (57) | `one_shot_retry` | 30.1 [21.0, 41.0] | 5/57 | 0.063 | 0.73 |
| Tier 2 (57) | cleansweep, gatekeeper | 37.4 [25.7, 53.5] | 0/57 | | |
| Tier 1 (10) | `one_shot_llm` | 30.2 [8.4, 62.3] | 3/10 | 0.25 | 0.50 |
| Tier 1 (10) | `one_shot_compile` | 24.1 [2.9, 57.9] | 0/10 | 1.0 | 0.13 |
| Tier 1 (10) | `one_shot_retry` | 30.3 [8.5, 62.4] | 0/10 | 1.0 | 0.63 |
| Tier 1 (10) | cleansweep, gatekeeper | 57.0 [13.3, 122.9] | 0/10 | | |

On AIDev every one-shot diff compiles, so the two variants equal `one_shot_llm` there.

Paired against cleansweep in gatekeeper mode on SWE-bench (`paired_tests.md`):
- **Hidden changes:**
  - only `one_shot_llm` differs: 9 vs. 0 on Tier 2 (exact McNemar p = 0.0039) and 3 vs. 0 on Tier 1 (p = 0.25);
  - `one_shot_compile`: 2 vs. 0 on Tier 2 (p = 0.5), 0 vs. 0 on Tier 1; `one_shot_retry`: 5 vs. 0 (p = 0.063), 0 vs. 0;
  - advisory, `guard_tests_only` and `tools_only`: p = 1.0.
- **Lines removed:**
  - `tools_only` removes fewer (Wilcoxon p = 0.016 on Tier 1, p < 0.001 on Tier 2);
  - `one_shot_llm` is not significantly different (p = 0.50 and 0.70).
- **Ablations (`ablation.md`):**
  - On the answer keys, the probes and the judge each keep the hidden checks unchanged where `guard_tests_only` and `tools_only` change them (0/2 vs. 2/2).
  - On SWE-bench, both modes and `guard_tests_only` apply the same edits. Those are almost all leftover files nothing imports, so there is little for probes to check.

## Why one-shot breaks things

`scripts/experiments/v1/exp_oneshot_breakages.py` (`results/summary/v1/oneshot_breakages.{csv,md}`) applies each
one-shot diff that changed hidden behavior in its workspace (Docker, no LLM) and classifies what
broke. There are 12 such runs, 3 on Tier 1 and 9 on Tier 2; the Tier 1 patches are also in
Tier 2 and got the same diffs, so 9 are distinct.

| What broke | Runs | Instances |
|---|---|---|
| the rewritten source file no longer parses (a stray `"` after the last line) | 10 | sympy-11618 × 3 (Tier 1 and 2), sphinx-7454 × 3, scikit-learn-10844 |
| an import the module still uses was removed (`import sys` in `django/http/response.py`) | 2 | django-11133 × 2 |
| a deleted file that code or tests use | 0 | |

- The stray quote comes from the model: its JSON reply ends the file's content with an escaped
  `\"`, and our code writes the content as given.
- Edit types over all Tier 2 patches:
  - one-shot edited source files on 37 of 57 patches (224 changed lines) and deleted 58 files
    (1,666 lines);
  - CleanSweep (gatekeeper) edited no source and deleted 78 leftover files (2,130 lines).

## The Guard as a filter on one-shot edits

`scripts/experiments/v1/exp_guard_on_oneshot.py` (`results/summary/v1/guard_on_oneshot.{csv,md}`) runs
`verify(agent patch, agent patch + one-shot diff)` with the tests and then runner-mode probes,
on every patch where one-shot applied edits. It ran in a frozen clone at 2ad7387 on
2026-10-27, 23:54 to 00:40.

| Set | Runs with edits | Breaking runs blocked | by compile | by tests | only by probes | Non-breaking runs blocked |
|---|---|---|---|---|---|---|
| Tier 1 | 8 | **3/3** | 3 | 0 | 0 | 0/5 |
| Tier 2 | 49 | **9/9** | 7 | 2 | 0 | 3/40 |

- The Guard would have stopped all 12 breaking one-shot runs. The compile check caught the
  stray quotes; Django's own tests caught the removed import (`test_headers_type`,
  `test_long_line`).
- The 3 non-breaking blocks are all `pylint-6903`. The probes' module check saw that
  `pylint.lint.run` lost the public name `UNUSED_PARAM_SENTINEL`. The model replaced the
  sentinel default of `do_exit` with `None`, so an explicit `do_exit=None` now behaves
  differently. That is a real change, but one the hidden tests don't exercise; we count it as
  a false alarm by our definition.

## Guard strength

How often `verify` (tests, then probes) rejects a change that should be rejected
(`scripts/experiments/v1/exp_guard_strength.py`, `results/summary/v1/guard_strength.csv`, 2026-10-27), with the
probes in direct and in runner mode (see [architecture.md](architecture.md#what-the-guard-checks)).

| Target | Experiment | n | Direct: caught (tests / only probes) | Runner: caught (tests / only probes) |
|---|---|---|---|---|
| toy repo | mutants in package functions | 20 | 20 (13 / 7) | |
| demo app | mutants in package functions | 20 | 18 (16 / 2) | |
| SWE-bench Tier 1 | mutants in agent-written functions (≤5 per patch) | 39 | 30 (30 / 0) | **36 (30 / 6)** |
| SWE-bench Tier 1 | PatchDiff recall: agent patch vs. developer fix (differs) | 3 | 0 | 0 |
| SWE-bench Tier 2 beyond Tier 1 | mutants in agent-written functions | 189 | | 135 (130 / 5) |
| SWE-bench Tier 2 beyond Tier 1 | PatchDiff recall | 14 / 15 | 4 (0 / 4) | 3 (0 / 3) |
| toy repo and demo app | false alarms on identical copies | 2 | 0 | |
| SWE-bench Tier 1 | false alarms on identical copies | 10 | 0 | 0 |
| SWE-bench Tier 2 beyond Tier 1 | false alarms on identical copies | 44 | | 0 |

Mutants use 5 operators: flip a comparison, swap + and -, add 1 to an int constant, swap
and/or, return None.
- **Runner mode gives the probes the project's setup.** On Tier 1 it catches the 6 Django
  `ModelAdmin.get_inline_instances` mutants that direct probes couldn't import without settings
  (36 of 39 instead of 30). The 3 survivors are the same `Point.distance` add/sub swap in the three
  sympy patches.
- **Tier 2 (47 patches beyond Tier 1, runner only):** the tests catch 130 of 189 mutants and the
  probes 5 more (astropy `SkyCoord.__getattr__` × 3, sphinx `_parse_annotation` and napoleon
  `_skip_member`). The largest groups of the 54 survivors are in sympy-12096 (13) and pylint-6903 (12). The 3
  django-11099 patches only change a class attribute, so there is nothing to mutate or probe.
- **PatchDiff recall:** every catch is a real difference.
  - `sphinx-10466` × 3: the agent removes duplicate locations, the developer's fix doesn't.
  - `flask-5014`/CodeStory: the agent rejects a whitespace-only blueprint name. Caught in direct
    mode only; the runner probes came from a separate request with no whitespace case.
  - The other differing patches pass the visible tests on both sides, and the probes found no
    input that separates them.
  - Runner mode also checked `sympy-12096`/OpenHands, which finished after the direct run (15 vs.
    14 patches).
- **False alarms:** none in either mode, including 44 Tier 2 patches.
- **Cost:** runner probes run the instance's test files too, about 4–5 minutes per Django patch
  instead of 2–3.
- **Lost probes:** in `pytest-5809`/OpenHands one probe request timed out, and in
  `sphinx-7910`/LearnByInteract the model's reply was malformed JSON four times. Those checks ran
  with 1–2 probe cases instead of about 9.

## AIDev sweeps

The five methods on the 20 AIDev repositories at their head sha (`exp_swebench.py` on
`data/splits/aidev_repos.json`; `exp_collect.py`, `exp_tables.py`, `exp_aidev_summary.py`;
`results/summary/v1/main_table.md` and `aidev_sweeps.md`). The Reviewer looks only at the code
agent pull requests wrote (first-parent blame). Hidden checks are pytest tests that a second
model (glm-5-3) writes for the public functions in up to six agent files, once per repository,
kept if stable over 3 runs.

- **20 repositories.** opendbc and pytorch_connectomics have no agent commit in the 300-commit
  history the scope comes from, so theirs comes from a longer one (999 and 338 commits). Their
  first, unscoped runs are listed apart in `aidev_sweeps.md` and left out of the tables.
  Fu-Jie/openwebui-extensions got no usable hidden tests, so hidden rates are out of 19.
- **The agent scope** covers a median 8% of a repository's Python lines (0.6% to 78%;
  `results/data_summary/aidev_scope.csv`, `scripts/data/data_aidev_scope.py`).
- **Lines removed leaves out formatting and unused imports.** A `ruff format` edit can add more
  lines than it removes: each CleanSweep method's 126 format edits added 1,719 lines net.
- **Integrity:** no test-run timeout or out-of-memory kill; 0 overload-suspect runs (first test
  run over twice the selection-time test time); 0 flaky hidden changes. Six grid runs failed on
  the repair timeout (fixed in #47): two were rerun, and the other four were unscoped runs that
  the scoped opendbc and pytorch_connectomics runs replace.

| method | lines removed (excl. format/imports) | edits | format edits | hidden changed | rolled back: tests / probes | McNemar p | Wilcoxon p |
|---|---|---|---|---|---|---|---|
| cleansweep, gatekeeper | 64.8 [12.1, 133.4] | 9.7 [4.3, 16.4] | 6.3 | 0.16 [0.00, 0.32] | 7 / 0 | | |
| cleansweep, advisory | 121.7 [18.9, 292.9] | 11.8 [5.3, 19.4] | 6.3 | 0.16 [0.00, 0.32] | 32 / 7 | 1.0 | 0.068 |
| `guard_tests_only` | 128.9 [20.1, 303.4] | 11.8 [5.5, 19.4] | 6.3 | 0.21 [0.05, 0.42] | 35 / (no probes) | 1.0 | 0.028 |
| `tools_only` | 117.2 [22.4, 276.8] | 5.7 [1.8, 12.1] | (1 ruff edit) | 0.21 [0.05, 0.42] | | 1.0 | 0.31 |
| `one_shot_llm` | **347.6 [170.7, 551.8]** | 4.3 [2.4, 6.5] | 0 | 0.11 [0.00, 0.28] | | 1.0 | **0.004** |

- **CleanSweep edits code here, not only files.** Advisory applied 87 dead-code removals, 3
  duplicate merges and 18 unused dependencies, besides 126 format edits, 1 unused import and 1
  leftover file. 35 of the dead-code removals are shotgun's Textual callbacks (below).
- **The probes rolled back 7 edits the tests passed.** Six are near-duplicates in Skill_Seekers
  (five MCP workflow tools and `_get_progress_dir`) that behave differently from the function
  they would be merged into. The seventh is pytorch_connectomics' `divide_rows`, which the
  duplicate finder matched with `divide_columns`: one divides rows, the other columns, and the
  probes found different outputs on a 2×2 input. In gatekeeper mode the judge moved 115 items out
  of the safe lane before any edit, `divide_rows` among them ("row-wise vs. column-wise
  division"). Without probes, `guard_tests_only` kept 3 of the 7 (`list_workflows`,
  `_get_progress_dir`, `divide_rows`; the others could not be applied after them). The
  projects' tests passed all three, and the hidden tests caught only `divide_rows`.
- **Hidden changes.** CleanSweep (either mode) changed hidden behavior on skillport,
  Telegram-Snowball-Sampling and Skill_Seekers. In every case the changed tests call functions
  the cleanup deleted as dead code: nothing in the project, its tests included, calls them.
  `guard_tests_only` also changed pytorch_connectomics (the duplicate merge above). `tools_only`
  changed the same three and slop-guard. `one_shot_llm` changed slop-guard (deleted benchmark
  scripts) and Usagi, where it deleted `src/config.py`, which the remaining modules import. One
  one-shot reply (Telegram) did not parse.

## AIDev: the v1.0 policies, re-scored

The runs above stay as run. Two Reviewer rules added after them are measured by re-scoring: the
edits a rule would have kept in the suggest lane are taken out of each run's final diff, and the
hidden checks rerun on the filtered diff with the same cached second-model tests
(`scripts/experiments/v1/exp_public_api_policy.py --policy public_api|framework|final --run`; Docker, no LLM).

- **Public API** (`reviewer.keep_public_api: auto`): dead-code edits on public names in package
  modules stay in the suggest lane.
- **Framework rule** (`reviewer.framework_callbacks: on`, table in
  `src/cleansweep/analysis/frameworks.py`): methods that Textual, Django, Flask/FastAPI,
  Click/Typer or pytest call by name, on classes that inherit from them, stay in the suggest lane.
- **Final policy**: both rules, the v1.0 defaults.

| method | hidden changed: as run → public API → framework → final | lines removed (excl. format/imports): as run → public API → framework → final |
|---|---|---|
| cleansweep, gatekeeper | 3/19 → 0/19 → 3/19 → **0/19** | 64.8 → 12.2 → 64.8 → 12.2 |
| cleansweep, advisory | 3/19 → 0/19 → 3/19 → **0/19** | 121.7 → 55.3 → 81.0 → 31.3 |
| `guard_tests_only` | 4/19 → 1/19 → 4/19 → 1/19 | 128.9 → 63.5 → 82.3 → 33.5 |

The public-API rule moves 47 to 54 edits per method in 7 repositories and takes out every
CleanSweep hidden change (exact McNemar p = 0.25, 3 vs. 0; Wilcoxon p = 0.018 on lines). The
framework rule moves 35 edits, all in shotgun, which the hidden tests did not see (next section).
`guard_tests_only`'s remaining change is the duplicate merge above, which neither rule covers.
Files: `aidev_public_api_policy.md`, `aidev_framework_rule.md`, `aidev_final_policy.md`.

## AIDev: framework callbacks and a UI check

shotgun is a Textual terminal app. 53 of the 85 detector-safe items in its runs are Textual
callbacks (`compose`, `on_mount`, `watch_*`, `action_*`): the framework calls them by name, so
nothing in the project does (`scripts/experiments/v1/exp_framework_callbacks.py`, `framework_callbacks.csv`).

- **Gatekeeper:** the judge vetoed 49 of the 53; none was kept (1 rolled back, 3 could not be applied).
- **Advisory and `guard_tests_only`:** all 53 reached the Guard; 35 were deleted with every test
  passing and 14 rolled back. Batches with callback edits failed 29 and 31 test runs (3.4 and 3.3
  of the runs' 11.0 and 13.0 hours).
- **UI check** (`scripts/experiments/v1/exp_shotgun_ui.py`, `shotgun_ui.csv`): each of shotgun's 44 Textual
  screen and widget classes is mounted headless (`App.run_test`) in the AIDev container, for the
  base and for every final diff, and its widget tree is compared; 32 render. As run, 17 classes
  changed under advisory, 16 under `guard_tests_only` and 18 under `tools_only` (gatekeeper and
  one-shot: 0). With the framework rule (and the final policy): 0. The remaining differences are
  whole classes deleted that nothing references; no module stopped importing.
- The second-model hidden tests call public functions, so they did not notice any of this.

## AIDev: dependency removals, verified

Removing a line from `pyproject.toml` uninstalls nothing, so the tests were the only check on
the 18 unused-dependency removals the sweeps applied. The Guard now reruns the tests with each
removed package's installed files moved aside, unless another installed package still requires
it (#2; `scripts/experiments/v1/exp_dependency_check.py`, `aidev_dependency_check.csv`). Re-checked this way,
**14 of 18 removals hold** (gatekeeper 13 of 15, advisory and `guard_tests_only` 14 of 18): 2 with
the package gone, 1 never installed, 11 still required by another package. **4 break tests**:
haliax `aqtp`, and Skill_Seekers `PyGithub`, `PyMuPDF` and `html5lib`. The hidden checks missed
them because those packages stayed installed. Outside AIDev containers the Guard marks such
removals "checked statically only".

## Self-sweep

CleanSweep on a copy of its own repository at a439dcd: the whole repository except
`tests/fixtures/`, `demo/`, `results/` and `data/`, with the offline test suite as the Guard's
tests (`scripts/experiments/v1/exp_self_sweep.py`, `results/summary/v1/self_sweep.csv`). Both modes found 139
items. The Guard kept all 124 format edits, 15 items stayed in the suggest lane in gatekeeper
mode (7 by the judge), and in advisory mode the probes rolled back the one duplicate merge that
reached the Guard (`kept_label` and `repos_label` print different text). We applied none of the
edits. The format edits used ruff's default line length, not the project's 100; the self-sweep
found this, #63 fixed it, and now only the hand-aligned `core/models.py` is flagged. The other
items are an unused public function, intended `eval` and XML uses, and two over-engineering
notes in `demo/`, which `reviewer.exclude` now keeps out of that review too.

## AIDev: Scheduler replay, removal requests, ranker

AIDev-pop (`data/raw/aidev/`): 666 Python repositories with ≥10 merged agent PRs; a seeded
sample of 120. A repository is kept if it installs in `python:3.11` (network cut before tests)
and runs ≥5 tests with ≥90% passing in under 10 minutes: **21 of 120**. The tables below use
**20 of 21 runnable repos** (one is left out of our released data files;
`results/data_summary/aidev_funnel.csv`, drop reasons in `aidev_filter.csv`). The replay uses each repository's last 300 first-parent commits (4,695 in
total, 626 from agent PRs) and the static detectors, measured at up to 40 commits per repository plus the last
(`scripts/experiments/v1/exp_replay.py`; Studio's Scheduler screen shows the curves).

**Scheduler trade-off** (20 of 21 runnable repos; mean and 95% bootstrap CI across
repositories; `scripts/experiments/v1/exp_scheduler_tradeoff.py`, `results/figures/v1/scheduler_tradeoff.png`):

| Policy | Slop-debt reduction vs. never sweeping | Test runs per repo (est.) | Sweeps per repo | Resurrection rate |
|---|---|---|---|---|
| after every agent PR | 61% [44, 75] | 15.7 [9.4, 23.4] | 4.8 | 0.19 |
| every 5 commits | 47% [31, 62] | 11.8 [5.7, 19.8] | 3.4 | 0.15 |
| daily (UTC, at the day boundary) | 87% [79, 94] | 27.7 [18.9, 38.6] | 9.5 | 0.22 |
| adaptive (slop > 2% of lines) | 39% [23, 55] | 7.1 [3.1, 12.4] | 1.0 | 0.17 |

Daily sweeps keep slop lowest but cost about 1.8× the test runs of sweeping after every agent PR,
and more of what they remove comes back. Sweeping after every agent PR sits in the middle on
both. The resurrection rate is the share of removed functions, classes and imports that still
exist at the last commit and are no longer flagged, because a later commit started using them.

**Removal requests.**
- Mining: 6,330 human review comments on .py files → 792 keyword matches → **535 removal requests** confirmed by the LLM. They come from 102 repositories, most often about dead code (224).
- Taxonomy: 15 clusters. Rules: 64 with lift ≥ 1.2 (`results/data_summary/`).
- The runnable repositories have almost no human review, so labels come from all repositories with a request: **9,416 units, 262 removal requests, 79 repositories** (static analysis only).

**Reviewer detection vs. those requests** (`results/summary/v1/reviewer_detection.csv`,
`results/data_summary/detection_by_category.csv`):
- Overall: precision 0.024, recall 0.075 (19 of 253 requested units are flagged by some detector).
- By kind of request, the detectors almost never flag a requested unit under its own category: dead code 1 of 119, wrappers 0 of 31, duplicates 0 of 20, leftover files 0 of 5, unused imports 0 of 3.
- When they do flag one, it is mostly under another category: requested dead code is flagged as a duplicate 5 times and as dead code once.
- The largest cluster of requests ("remove, line, just, suggestion", 242 requests) is about lines inside functions (comments, try/except blocks, assertions). The unit-level detectors don't look at those: recall 0.025.

**Ranker: a negative result** (`results/summary/v1/ranker_report.md`).
- Calibrated gradient boosting, cross-validated by repository, on the 9,416 labeled units.
- Out-of-fold scores: AUC 0.607; average precision 0.047 against a base rate of 0.028; Brier 0.0269 against 0.0271 for always predicting the base rate.
- Unit size (`loc`) carries most of the signal: the request rate rises from 0.9% for the smallest quarter of units to 5.5% for the largest. That is about where reviewers look.
- It doesn't measure safety:
  - the label is "a reviewer asked to remove this", not "removing it keeps behavior";
  - unreviewed units are not "must keep";
  - its scores (median 0.026, at most 0.20) never reach the Reviewer's 0.6 batching threshold.
- So the Reviewer keeps its category priors.

## v2: the agent team

The agent team (`cleansweep clean`, `method=agentic`, safe mode, `qwen36-35b-a3b`) against v1's
sweep in gatekeeper mode, on the same targets, plus the v2-only experiments. Hidden changed = the
hidden checks give a different result after the cleanup; neither system ever sees them. Code
lines removed counts lines removed from non-test Python files in the final diff, measured the
same way for both (v1 from its archived reports). Commits: the answer keys and AIDev ran at
c68fcdc, SWE-bench at 7237ccc (with the test-status fix, #118), probe strength at f84d568, and
the injection benchmark (every seed, with its plant checks), its ablations and the real-project
ablation at 106c952 ([experiments.md](experiments.md) has the commands).
Tables: `results/summary/v2/`; `bash scripts/reproduce_tables.sh` rebuilds `eval_table`,
`eval_paired`, `ablations`, `injection_summary`, `injection_summary_seeds12`, `injection_seeds`,
`injection_paired`, `real_ablation` and `real_ablation_tests` from the per-run CSVs.

### The team against v1

`eval_table.csv`, `eval_paired.csv`: mean [95% bootstrap CI] per target.

| target set | runs | team verdicts: everything runs / nothing applied / not verified | team code lines removed | team hidden changed | v1 code lines removed | v1 hidden changed | LLM requests, team / v1 | tokens, team / v1 | minutes (median), team / v1 |
|---|---|---|---|---|---|---|---|---|---|
| answer keys (toy, demo ×3) | 6 | 6 / 0 / 0 (60/60 planted) | 57.0 [51.7, 62.3] | 0/6 | 57.0 [51.7, 62.3] | 0/6 | 41.5 / 5.5 | 56,770 / 31,679 | 1.7 / 4.8 |
| SWE-bench Tier 1 | 10 | 7 / 3 / 0 | 37.5 [9.2, 73.1] | 0/10 | 37.5 [9.2, 73.1] | 0/10 | 11.8 / 0.8 | 16,275 / 2,847 | 1.1 / 1.5 |
| SWE-bench Tier 2 subset | 20 | 16 / 4 / 0 | 15.2 [8.2, 22.8] | 0/20 | 15.2 [8.2, 22.8] | 0/20 | 9.1 / 1.4 | 10,371 / 6,326 | 1.1 / 2.4 |
| AIDev | 6 | 4 / 2 / 0 | 46.7 [1.3, 134.5] | 0/6 | 256.2 [116.8, 400.7] | 3/6 | 73.0 / 17.2 | 143,426 / 116,186 | 11.1 / 78.5 |

Paired with v1 on the same targets (and repeats): the same code lines in total on the answer
keys (342), Tier 1 (375) and the Tier 2 subset (303), and no discordant hidden result; on AIDev
280 against 1,537 lines, hidden changed only with v1 on 3 (McNemar p = 0.25, Wilcoxon p = 0.063,
n = 6). The team removed about a fifth of v1's code lines on AIDev, so part of its safety there is
caution.

- **SWE-bench.** Every removal by either system deletes a whole scratch file the coding agent
  left at the repository root: `reproduce*.py`, `edge_cases.py`, `test_*` reproduction scripts,
  `test_package/`, `test_reproduce/`, and on django-11095 (OpenHands) a whole `test_app/` Django
  project plus `test_inlines.py` (313 lines). There v1 also deleted a 25-line root
  `test_settings.py` the team kept, so the code lines match and all lines removed differ (338
  against 313). We read every diff (LLM-judged: the coding assistant that ran the evaluation);
  none is wrong. Every baseline ran tests (5 to 428 passing).
  The first team runs on SWE-bench (`results/raw/v2_eval/tier1_first`, `tier2_first`) are not
  reported: the SWE-bench workspace never stored per-test results, so every baseline had 0
  passing tests and 16 of 30 runs ended "everything runs" with nothing tested (#118). Five Tier 1
  reruns that ran before the fix reached the run clone are kept as `tier1_unfixed_rerun` and not
  reported either.
- **AIDev.** The six repositories were chosen from v1's results before the v2 runs: the three
  where v1 changed hidden behavior (skillport, Telegram-Snowball-Sampling, Skill_Seekers), the two
  where its probes and judge mattered (pytorch_connectomics, shotgun) and one where it applied
  nothing (imgviz). v1's three hidden changes come from deleting functions nothing in the
  project calls that the second model's tests use (`format_score`, `sanitize_filename`, ...).
  The team kept them because its Auditor runs v1's detectors with the v1.0 public-API rule
  ("public name with no caller in the project; may be public API"), which v1's recorded runs
  predate; its Investigator found no use either. With that rule, v1 changes 0 of 19 on the 20
  repositories ([AIDev: the v1.0 policies, re-scored](#aidev-the-v10-policies-re-scored)).
- **Reading the team's diffs** (by the coding assistant that ran the evaluation, so not
  independent): skillport (three `return bool(...)` simplifications and a comment) and
  Skill_Seekers (an unused method) are fine; shotgun (264 lines) deletes two unused methods and an
  unreferenced `FeedbackScreen` class, plus two debatable edits (a commented-out toggle marked
  "hidden for now", and `feedback.py` left with only its imports). **One edit is wrong**: on
  pytorch_connectomics the team removed `pdb.set_trace()` under `if self.debug_on_nan:`, an
  opt-in debugger, so the option no longer stops. No test or hidden check enters that path. Since
  #124 a debugger call behind a condition is only suggested; the runs above predate it. Rerun at
  106c952 (after #124; `results/raw/v2_eval/aidev_after124/`): all 153 candidates went to the
  suggest lane, the conditional `pdb.set_trace()` among them, so nothing was applied and the
  hidden checks did not change (52 LLM requests, 15.8 minutes).
- **Cost.** The team makes more, shorter LLM requests (about 1,400 tokens each on the answer keys
  against v1's 5,800) and finishes sooner: its investigations run three at a time, v1's judge
  waits for long answers.

### Slop-injection benchmark

`injection_summary.csv`, `injection_seeds.csv` and `injection_paired.csv` are built from
`injection.csv`, which has one row per plant, method and seed.

- **Projects:** the toy repository and 9 AIDev repositories: easy-code-reader, slop-guard, ai-goofish-monitor, Telegram-Snowball-Sampling, mcp-nixos, dropkit, wove, CORAL and haliax.
- **Plants:** each project-seed gets 7 planted items and 2 traps.
  - Each plant is checked to be a right answer, and each trap to really differ.
  - The hidden test has to pass on the injected project before any cleanup; otherwise the modules are drawn again.
- **Seeds:** the team, the no research squad and the single agent ran seeds 1–3 (30 runs each). v1, the one-shot LLM and the other ablations ran seeds 1 and 2 (20 runs).
- **One-shot scope:** the one-shot LLM sees the files the plants commit changed.
- **Code:** 106c952, in the frozen clone `../cleansweep-runs-v2c`.

| method | runs | leftover file | dead code | exact duplicate | unused import | debug print | commented-out code | unused dependency | all planted | traps removed | hidden changed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| team | 30 | 30/30 | 29/30 | 0/30 | 26/30 | 30/30 | 30/30 | 25/30 | 170/210 (0.81) | 0/60 | 0/30 |
| no research squad | 30 | 30/30 | 28/30 | 0/30 | 29/30 | 30/30 | 30/30 | 29/30 | 176/210 (0.84) | 2/60 | 2/30 |
| single agent | 30 | 30/30 | 26/30 | 0/30 | 27/30 | 9/30 | 6/30 | 16/30 | 114/210 (0.54) | 16/60 | 16/30 |
| v1 | 20 | 20/20 | 19/20 | 0/20 | 19/20 | 0/20 | 0/20 | 20/20 | 78/140 (0.56) | 1/40 | 1/20 |
| one-shot LLM | 20 | 19/20 | 19/20 | 19/20 | 14/20 | 18/20 | 18/20 | 0/20 | 107/140 (0.76) | 36/40 | 19/20 |

Per seed (`injection_seeds.csv`): the share of planted items removed per run, as a mean with a
95% bootstrap CI over project and seed.

| method | seed 1 | seed 2 | seed 3 | pooled |
|---|---|---|---|---|
| team | 0.814 [0.757, 0.857] | 0.800 [0.743, 0.857] | 0.814 [0.757, 0.857] | 0.810 [0.771, 0.843] |
| no research squad | 0.843 [0.814, 0.857] | 0.814 [0.757, 0.857] | 0.857 [0.857, 0.857] | 0.838 [0.814, 0.857] |
| single agent | 0.471 [0.414, 0.543] | 0.586 [0.486, 0.686] | 0.571 [0.457, 0.671] | 0.543 [0.486, 0.600] |
| v1 | 0.557 [0.529, 0.571] | 0.557 [0.529, 0.571] | | 0.557 [0.536, 0.571] |
| one-shot LLM | 0.843 [0.814, 0.857] | 0.686 [0.514, 0.800] | | 0.764 [0.671, 0.829] |

Paired by project and seed (`injection_paired.csv`; Wilcoxon on planted items removed, exact
McNemar on hidden changes and on removing a trap):

| team against | pairs | planted removed | Wilcoxon p | hidden changed only with the team / only with the other | McNemar p |
|---|---|---|---|---|---|
| no research squad | 30 | 170 vs 176 | 0.063 | 0 / 2 | 0.5 |
| single agent | 30 | 170 vs 114 | < 0.0001 | 0 / 16 | < 0.0001 |
| v1 | 20 | 113 vs 78 | < 0.0001 | 0 / 1 | 1.0 |
| one-shot LLM | 20 | 113 vs 107 | 0.55 | 0 / 19 | < 0.0001 |

- **Traps:** every trap that the single agent, the no research squad and v1 removed is the framework callback, `visit_Name`, which `ast.NodeVisitor` calls by name. None of them merged the near-duplicate. The one-shot LLM removed both traps in 18 of 20 runs.
- **What the team misses:**
  - No method that works from v1's detectors removed a planted exact duplicate. The one-shot LLM merged 19 of 20.
  - Apart from the duplicates, the team missed 4 unused imports, 5 unused dependencies and 1 dead function.
- **Where the team's gain over v1 comes from** (`injection_summary_seeds12.csv`, seeds 1 and 2, which both ran): 113 against 78 of 140 planted items. The whole gain is in the two kinds the line-level detectors find: debug prints (20 against 0 of 20) and commented-out code (20 against 0), for which v1 has no detector. v1 removed a few more unused dependencies (20 against 17) and unused imports (19 against 17); leftover files, dead code and duplicates are level. The single agent removes few of the line-level kinds (9 and 6 of 30).
- **Projects left out** (`EXCLUDED` in `exp_inject.py`):
  - imgviz: its hidden test failed before any cleanup, so it was replaced by mcp-nixos.
  - openwebui-extensions: its hidden test failed on all 3 injected draws, because the plugin modules import `open_webui`, which the project does not install. It was replaced by haliax.
  - skillport and chatlas: fewer than three importable modules to plant in.
- **Runs spoiled by sleep:**
  - Three laptop sleeps (2026-11-03 and 04) spoiled runs whose wall clock ran through them. Each was rerun, and the rerun replaces it.
  - The spoiled runs are kept in `results/raw/inject_superseded/sleep_*` and are not reported.
  - The earlier seed-1 run, before the plant checks (f84d568), is superseded in the same way.

### Ablations

`ablations.csv`: one part of the team switched off. On the answer keys, 6 runs each. The columns are planted items found of 60, runs with a hidden change, mean LLM requests and median minutes.

| variant | found | hidden | LLM requests | minutes |
|---|---|---|---|---|
| team (LLM Manager) | 60/60 | 0/6 | 41.5 | 1.7 |
| rule-based Manager | 60/60 | 0/6 | 37.2 | 1.8 |
| no research squad | 60/60 | 0/6 | 11.7 | 1.3 |
| broadcast messages | 60/60 | 0/6 | 43.7 | 1.9 |
| artifacts inlined | 60/60 | 0/6 | 41.7 | 1.9 |
| no lessons | 57/60 | 0/6 | 43.2 | 1.5 |
| no coverage guidance | 60/60 | 0/6 | 42.8 | 1.6 |
| single agent | 54/60 | 4/6 | 36.2 | 6.0 |

**Single agent on the answer keys:**
- It changed hidden behavior in 4 of 6 runs, every time by merging the near-duplicate rounding helper (the trap every visible test passes).
- On the demo app it also deleted command functions the app calls by name: all seven in one run, two in each of the others. So its diff failed visible tests every time, which it reported as "not verified".
- On the toy repository it reported "everything runs" all three times.

On the injected set, the same project-seed runs as the benchmark above. The columns are planted items removed, traps removed, runs with a hidden change, mean LLM requests and median minutes.

| variant | runs | removed | traps | hidden | LLM requests | minutes |
|---|---|---|---|---|---|---|
| team (LLM Manager) | 30 | 170/210 | 0/60 | 0/30 | 92.3 | 4.5 |
| rule-based Manager | 20 | 113/140 | 0/40 | 0/20 | 87.5 | 2.3 |
| no research squad | 30 | 176/210 | 2/60 | 2/30 | 9.7 | 4.4 |
| broadcast messages | 20 | 113/140 | 0/40 | 0/20 | 91.2 | 2.2 |
| artifacts inlined | 20 | 112/140 | 0/40 | 0/20 | 91.2 | 2.3 |
| no lessons | 20 | 111/140 | 0/40 | 0/20 | 93.7 | 4.3 |
| no coverage guidance | 20 | 113/140 | 0/40 | 0/20 | 91.0 | 2.2 |
| single agent | 30 | 114/210 | 16/60 | 16/30 | 84.9 | 4.9 |
| adaptive investigation (seed 1) | 10 | 55/70 | 0/20 | 0/10 | 78.6 | 7.6 |

Runs shared the machine with other runs in different mixes, so the minutes do not compare across rows. On the same two seeds the team removed 113 of 140.

- **Single agent:**
  - It deleted the framework callback (`visit_Name`) in 16 of its 30 runs, and every one changed the hidden test.
  - It removed 9 of the 30 debug prints and 6 of the 30 commented-out blocks, against the team's 30 each.
- **No research squad:**
  - It removed 6 more planted items than the team at about a tenth of the requests (Wilcoxon p = 0.063).
  - It removed the framework callback twice (ai-goofish-monitor seed 2, easy-code-reader seed 3); the team never did.
  - Without the squad, v1's detectors go straight to the development squad, one package per safe item.
- **Other variants:** the rule-based Manager, broadcast messages, inlined artifacts, no lessons and no coverage guidance stay within two items of the team on the same seeds, and none removed a trap.

On these benchmarks the research squad adds requests, not recall. On real projects the picture
differs (see the real-project ablation below).

### Diff audit

The audit asks whether a kept edit changes behavior anyone could observe, including what no test checks.

- **Auditor:** an independent model (`glm-5-3`, never the agents' model) reads every kept code edit of every method and target set, with 3 votes. It sees the code around the edit at the run's starting commit and where the removed names appear. It never sees the method or the agents' verdicts.
- **Checks:** every "yes" or "unsure" is checked under the written rubric ([experiments.md](experiments.md#v2-diff-audit)) and recorded with its evidence and kind (`diff_audit_checks.csv`).
- **Tiers:** each verdict has one.
  - **Confirmed:** a targeted test that passes before the edit and fails after, run in that run's own environment; or shotgun's UI check; or the injection key's or agent patch's rule.
  - **Reading (LLM-judged):** the code around the edit and every use of the removed names, read by the coding assistant that ran the evaluation, not a person.

| verdict | checks | confirmed | reading (LLM-judged) |
|---|---|---|---|
| wrong | 147 | 88 (70 targeted test, 16 injection-key rule, 2 UI check) | 59 |
| debatable | 252 | | 252 |
| fine | 162 | 88 (66 injection-key rule, 22 agent-patch rule) | 74 |

Each of the 129 wrong verdicts that no rule or UI check settled has a targeted test folder (`results/raw/diff_audit/tests/`).

- The 59 that stay readings each record the observed reason no test could run:
  - the project does not install what the code imports: CORAL's graders and seeds import harbor, torch or numpy;
  - a build hook runs only when hatchling builds the package;
  - a removed dependency stays installed in the run's environment because another package requires it.
- A copy of a checked edit (the same change in another seed or run) carries the reading. The original's test runs again on each copy, in the copy's own run.

- **Lower bounds, not biased by method:** Only flagged edits are checked, so the wrong counts are lower bounds. The auditor never sees the method, so its flags are not biased by who made the edit, but how loose the bound is differs by method: it voted "no" on 82% of the team's injected edits and 60% of v1's and the single agent's. The checks after a flag saw which run an edit came from; the confirmed tier rests on tests and rules.

Wrong edits of the kept code edits, all tiers, with the confirmed count in brackets (`diff_audit.csv`):

| target set | team | no research squad | single agent | v1 | one-shot LLM |
|---|---|---|---|---|---|
| injected, all seeds | 18 of 804 (12) | 27 of 825 (22) | 63 of 489 (50) | 48 of 610 (13) | 5 of 75 (5) |
| real-project ablation | 0 of 14 | 4 of 20 (3) | 17 of 65 (12) | | |
| AIDev (six repositories) | 1 of 10 (1) | | | 8 of 53 (5) | |

- **Team against v1, injected set:** about the same on the confirmed tier, 12 of 804 (1.5% [0.8, 1.9]) against 13 of 610 (2.1% [1.5, 3.8]); lower across all tiers, 2.2% [1.5, 2.8] against 7.9% [2.6, 9.0], though 35 of v1's 48 are readings and the intervals overlap slightly. The team's 12 confirmed are all targeted tests; v1's 13 are 12 targeted tests and 1 injection-key rule.
- **Other target sets:** the only wrong edits on the answer keys, SWE-bench and the case studies are the single agent's 4 of 57 on the answer keys (all confirmed).
- **Other ablations, injected set:** from 7 of 434 (artifacts inlined) to 12 of 545 (the rule-based Manager).

- **Kinds** (`diff_audit_types.csv`):
  - Of the team's 18 injected wrong edits:
    - 14 are dynamic handlers or stubs: code a framework, grader or loader calls by name.
      - 9 are methods: CORAL's eval-viewer `do_GET` (2) and `do_POST` (3), and torch and Lightning `forward` methods (4).
      - 5 are classes: the `KernelBuilder` class of a published kernel demo (3) and dropkit's hatchling build hook class (2);
    - 3 are dependency removals;
    - 1 changes logic.
  - The single agent's 63 spread more widely: dynamic handlers or stubs 34, public names 10, changed logic 8, dependencies 8, deleted files 3.
- **What the checks missed:** none of the team's 18 failed a test, probe or hidden check in its run. This is the gap between "everything runs" and "nothing changed".
- **What the audit does not check:**
  - Only edits the auditor flagged are checked. The 1,223 of 1,784 audited edits it voted "no" are not, so the wrong counts are lower bounds.
  - Stale files, possible, not measured: until v2.1.1 the containers saw the workspace through Docker Desktop's file sharing, which can briefly show a deleted file or a replaced file's old content. A stale read in a Guard check, a hidden check or a targeted test would have hidden a change; the logs cannot tell whether one happened. The targeted tests of the injected toy repository's seeds 2 and 3 also ran on seed 1's tree.
  - On the demo app it voted "no" on all 11 of the single agent's deletions of command functions (`bookshelf/commands.py`), which the app dispatches through `getattr`. Those runs failed visible tests (Ablations above), but the audit counts these edits as neither wrong nor checked.
- **Debatable:**
  - 252 edits remove code reachable only from outside the project.
  - 158 of them are in CORAL's task seed folders, mostly `seed/solution.py` stubs whose only method raises `NotImplementedError`.
  - They are reported apart, never as wrong.
- **Rubric applied after the first checks:**
  - The rubric was written down after the first 335 checks, and each earlier verdict was read against it again.
  - 72 verdicts moved from wrong to debatable, mostly the CORAL seed stubs (`diff_audit_rubric_changes.csv`).
- **Calibration:** the blinded calibration sheet of 20 checks has not been filled in by a person, so the readings are not checked by a human.

### The framework rule, re-scored

`inject_rule.csv` reports each method as run and with the rule.

- **Why the rule was extended:** most of the team's wrong edits were code a framework calls by name. So the framework-callback rule now also covers:
  - `http.server` handlers;
  - `ast.NodeVisitor`;
  - PyTorch and Lightning modules;
  - hatchling build hooks (#139).
- **Trigger, checked on the final data:** the rule stays if such edits are at least half of the team's injected wrong edits. They are 14 of 18 (8 of them confirmed).
- **Re-score:** the runs were made without the rule, so each of the 220 injected runs (210, and adaptive investigation's 10 later) was re-scored with it.
  - The kept edits the rule would have sent to the suggest lane are taken out.
  - The rest of the run's diff is applied to the starting commit, and the hidden test runs on it in a fresh workspace.
  - The audit's verdicts carry over to the edits that stay.

| method | runs | edits moved | planted removed | traps removed | hidden changed | wrong (confirmed) |
|---|---|---|---|---|---|---|
| team | 30 | 12 | 170 → 170 | 0 → 0 | 0 → 0 | 18 → 9 (12 → 7) |
| no research squad | 30 | 10 | 176 → 176 | 2 → 0 | 2 → 0 | 27 → 20 (22 → 17) |
| single agent | 30 | 25 | 114 → 114 | 16 → 0 | 16 → 1 | 63 → 47 (50 → 34) |
| rule-based Manager | 20 | 8 | 113 → 113 | 0 → 0 | 0 → 0 | 12 → 6 (8 → 5) |
| broadcast messages | 20 | 5 | 113 → 113 | 0 → 0 | 0 → 0 | 10 → 6 (8 → 5) |
| artifacts inlined | 20 | 3 | 112 → 112 | 0 → 0 | 0 → 0 | 7 → 5 (6 → 4) |
| no lessons | 20 | 3 | 111 → 111 | 0 → 0 | 0 → 0 | 10 → 8 (7 → 6) |
| no coverage guidance | 20 | 5 | 113 → 113 | 0 → 0 | 0 → 0 | 9 → 5 (7 → 4) |
| v1 | 20 | 15 | 78 → 78 | 1 → 0 | 1 → 0 | 48 → 37 (13 → 8) |

- **Effect:** the rule moves edits in 38 of the 220 runs and costs no planted item.
- **What it moves for the team:** the 9 methods. The rule marks methods (a hatchling hook's `initialize`, for example), not a whole class. So the 5 class deletions stay, along with the 3 jinja2 removals and the dropkit logic change: the `KernelBuilder` demo and dropkit's build hook class are deleted whole.
- **The remaining hidden change:** with the rule, the single agent's one is slop-guard, seed 1, where the hidden test still fails on the rest of that run's diff.
- **Reporting:** the reported numbers everywhere else stay as run.
- **In-sample:** the rule was extended after seeing these failures and is re-scored on the same runs, so 18 → 9 is an optimistic estimate of what it saves. Fresh projects or seeds would test it.

### Real-project ablation

The test of whether investigation helps on real projects (`real_ablation.csv`, one row per run
in `real_ablation_runs.csv`).

- **Setup:**
  - The team, the team without its research squad and the single agent each clean the five case-study projects once.
  - Safe mode, a 120-minute budget each; Skill_Seekers gets 300 LLM requests, as in its case study.
  - The single agent's budget starts after its test baseline, and its shotgun run took 144 minutes in all.
  - Code at 106c952.
- **Lines removed:** net lines (deleted minus added) in each final diff, counted the same way for the three.
- **Reviewer:** the LLM reviewer (an independent model, blinded, 3 votes) judges each kept change. Its acceptance is LLM-judged.
- **Wrong and debatable:** the diff audit's checked verdicts on the kept code edits, with the confirmed tier in brackets.
- **UI check:** shotgun's UI check ran on all three final diffs.

| method | verdicts | packages kept / rolled back | lines removed | LLM reviewer accepts kept changes (LLM-judged) | wrong of kept code edits (confirmed) | debatable (reading, LLM-judged) | shotgun UI check | LLM requests (mean) | minutes (mean) |
|---|---|---|---|---|---|---|---|---|---|
| team | everything runs 4, nothing applied 1 | 16 / 20 | 315 | 12/14 (2 unsure) | 0 of 14 | 0 | ok (46 classes) | 129.8 | 19.0 |
| no research squad | everything runs 5 | 22 / 35 | 653 | 13/21 (1 unsure) | 4 of 20 (3) | 0 | ok (46 classes) | 15.8 | 35.3 |
| single agent | everything runs 5 | 73 / 9 | 1,020 | 44/65 (8 unsure) | 17 of 65 (12) | 15 | `AttachmentBar` changed | 83.2 | 47.1 |
| adaptive investigation | everything runs 4, nothing applied 1 | 19 / 20 | 593 | 12/17 (2 unsure) | 2 of 17 (1) | 0 | ok (46 classes) | 127.2 | 32.5 |

Per project (packages kept / net lines):

| project | team | no research squad | single agent | adaptive investigation |
|---|---|---|---|---|
| this repository | 0 / 0 (its one package rolled back) | 1 / 141 | 14 / -46 (added 46 lines) | 1 / 141 |
| slop-guard | nothing applied | 0 / 0 (3 rolled back) | 9 / 28 | nothing applied |
| Skill_Seekers | 7 / 11 | 10 / 89 | 25 / 372 | 8 / 29 |
| shotgun | 8 / 298 | 9 / 417 | 18 / 527 | 9 / 417 |
| Telegram-Snowball-Sampling | 1 / 6 | 2 / 6 | 7 / 139 | 1 / 6 |

- **The team:**
  - The audit flagged none of its 14 kept code edits, so none was found wrong or debatable. The 14 come from three projects: it kept no code edit on this repository and applied nothing on slop-guard.
  - The reviewer accepted 12 of the 14 kept changes it decided on.
  - It rolled back more packages than it kept (20 against 16).
- **No research squad:** the detector lanes decide what is safe, so it tried more and kept more at an eighth of the requests. But 4 of its 20 kept code edits are wrong:
  - It deleted this repository's `scripts/experiments/v2/exp_collect_v2.py`, the documented script that writes `eval_runs.csv`.
  - It deleted Skill_Seekers' `resolve_playlist`. `VideoScraper.run` imports it, so every video run fails.
  - It merged `infer_description_from_html` into the identical EPUB function through an `src.skill_seekers...` import that fails once the package is installed.
  - It deleted shotgun's `CustomBuildHook`, the build hook `pyproject.toml` declares, so building the package fails. This one is by reading: hatchling is not installed in the run's environment.
  - The first three are confirmed by targeted tests.
- **Single agent:** it removed the most and broke the most. 17 of 65 kept code edits are wrong.
  - 12 are confirmed, 10 by targeted tests and 2 by the UI check:
    - on this repository: the Studio messages that print the URL and the build commands, documented in the user guide; `checked[checked.removal == True]` rewritten as `checked[checked.removal]` where the column holds `None`; and `value is False` turned into `not value` for the install setting;
    - on shotgun: the pydantic validator of `SHOTGUN_PIPX_SIMULATE`, the command-palette hook, and `AttachmentBar.compose` and `watch_state`, which Textual calls by name (the UI check caught the last two);
    - on Skill_Seekers: html5lib (the lenient-parser fallback a test requires) and a bundled workflow preset.
  - 5 are by reading:
    - four core dependencies that `skill-seekers doctor` imports by name and that a fresh install no longer gets (the click removal is debatable, because a fresh install still gets click);
    - shotgun's build hook.
  - On this repository it added 46 lines net.
- **Adaptive investigation** (`core.agents.investigate: adaptive`, #145): only the candidates the rules call uncertain go to an Investigator. Those are near-duplicates and wrappers, dependency removals, framework methods, dynamic-use risks and public dead code in a package.
  - **Runs:** chain I, at 1b98820 in `../cleansweep-runs-v2d`, after the other three methods, with the same targets and budgets.
  - **Routing:** on real code nearly every candidate is uncertain: shotgun 378 of 387, this repository 36 of 40, Telegram 16 of 17, slop-guard 17 of 17. So it used 127.2 LLM requests per project against the team's 129.8 (Skill_Seekers 300, its cap).
  - **Safety:** 2 of its 17 kept code edits are wrong.
    - The deleted `exp_collect_v2.py`, confirmed by a test.
    - shotgun's build hook, by reading.
    - On this repository and shotgun it kept exactly what the no research squad kept, and both wrong edits are that squad's.
  - **Review and UI:** the reviewer accepted 12 of 17 (LLM-judged), and shotgun's UI check is ok.
  - **Injected set, seed 1** (10 projects, the same plants as every other method):
    - planted items removed: 55 of 70, against the team's 57 (Wilcoxon p = 1.0), with no trap and no hidden change;
    - LLM requests: 78.6 per run, against 91.8;
    - wrong: 4 of its 188 kept code edits (3 confirmed), against the team's 6 of 275 on that seed. All 188 are edits another method made on the same plants.
  - **Decision (DECISIONS):** the default stays `all`. The bar was the team's safety on real projects at no more than half the requests, and adaptive meets neither part.
- **Tests** (`real_ablation_tests.csv`): Fisher's exact test, two-sided, of each method's wrong share of kept code edits against the team's 0 of 14.

| team against | all tiers | p | confirmed | p |
|---|---|---|---|---|
| no research squad | 4 of 20 | 0.13 | 3 of 20 | 0.25 |
| single agent | 17 of 65 | 0.03 | 12 of 65 | 0.11 |
| adaptive investigation | 2 of 17 | 0.49 | 1 of 17 | 1.0 |

- **What this shows:** the research squad's effect on real code is suggested, not established. The test pools edits, but they cluster by project: every wrong edit of the three methods is in this repository, shotgun or Skill_Seekers. The strong claims rest on the 30 paired benchmark runs above.
- **Caveats:**
  - No wrong edit failed a test or probe in its run. Every run ended "everything runs", or "nothing applied" (the team on slop-guard).
  - One run per project and 14 to 65 kept code edits per method make this a small sample.
  - The single agent's 120 minutes start after its test baseline (`solo.py`; 14 minutes on shotgun); the team's start at the beginning of the run.

### Probe strength

`probe_strength.csv`: v1's Guard-strength experiment with the coverage-guided probes (the same
mutants, sampled with v1's seed and limits, and the same PatchDiff patches).

| target set | mutants caught | by the tests | only by the probes | PatchDiff recall |
|---|---|---|---|---|
| toy repo (direct) | 19/20 | 15 | 4 | |
| demo app (direct) | 18/20 | 15 | 3 | |
| SWE-bench Tier 1 (runner) | 36/39 | 30 | 6 | 0/3 |
| SWE-bench Tier 2 subset (runner) | 53/81 | 52 | 1 | 3/18 (all by the probes) |

`probe_strength_vs_v1.csv` (`exp_probe_strength.py --compare`): matched one by one with v1's
records, the two catch the same 117 of 163 mutants and patches, except one toy mutant that v1's
probes caught and these did not; 18 Tier 2 records have no v1 counterpart.

### Manager scenarios

`manager_scenarios.csv`: four small projects built so that one decision is right, 3 runs each of
the LLM-guided Manager and the rules alone.

| scenario | right decision | LLM Manager | rules |
|---|---|---|---|
| conflict | go back to EXECUTE and undo only the package that broke a test | 3/3 | 3/3 |
| budget | stop at 85% of the test-run cap and deliver the verified packages | 3/3 | 0/3 (went on) |
| no baseline | change nothing (stop or plan only) and say why | 3/3 | 3/3 |
| rollbacks | go back to INVESTIGATE or replan once half the packages rolled back | 0/3 (went on) | 0/3 (went on) |

Every run of both ended no worse than its baseline.

### Case studies

Safe mode unless noted; records in `results/raw/case_studies/` (local). LLM review =
"LLM-reviewer acceptance (independent model, blinded)" (`llm_review_acceptance.csv`): accept /
reject / unsure, 3 votes per row, the model sees only the code, the change and the facts. It is
an LLM's judgment; no human checked it.

| project | tests before → after | lines removed | result | LLM review: applied | suggestions |
|---|---|---|---|---|---|
| this repository | 335 → 335 | 0 (its one package rolled back) | everything runs | | 9 / 16 / 3 |
| slop-guard | 182 | 0 | nothing applied (thorough: everything runs, its one package rolled back) | | 12 / 18 / 5 |
| Skill_Seekers | 4,442 → 4,442 | 11 | everything runs | 6 / 0 / 1 | 14 / 21 / 5 |
| shotgun | 2,254 → 2,256 | 298 | everything runs | 6 / 0 / 2 | 2 / 37 / 1 |
| Telegram-Snowball-Sampling | 27 → 27 | 6 | everything runs | 0 / 1 / 0 | 21 / 10 / 2 |

"Everything runs" means the tests ran and nothing got worse, also when every package rolled
back. The reviewer rejected Telegram's one applied change (an inlined one-use wrapper) by reading
the project's failing test, which also failed before the cleanup, as caused by it; it agreed with
the checks on the two merges thorough mode tried and rolled back there.

### Detection and watch

- **Detection** (`detection.csv`): of 163 removals human reviewers asked for in 116 AIDev pull
  requests, v1's static detectors flag 19 (precision 0.024, recall 0.117); the team's Auditor,
  with the line-level detectors, 24 (0.027, 0.147).
- **Watch** (`watch_replay.csv`, the 20 AIDev histories, static detectors): the watch rule (clean
  at 2% slop, after 3 new items or 20 commits) leaves a mean slop debt of 41.1 open items summed
  over the measured commits, against 693.1 for a daily sweep and 9,863.2 for never sweeping, at
  68.7 estimated test runs against 27.7. Held to the adaptive policy's test runs it leaves
  8,841.1, worse than every policy but never sweeping.

## v3: the evaluation (Phase 3), frozen 2026-11-13 12:00

Phase 3 tests the agent team in settings it was not tuned on, against an outside agent, under one
time cap and one LLM budget for every method. Every hypothesis, metric and threshold was fixed in
`docs/preregistration_v3.md` before the first main run; its Deviations section lists every change
since (nine, each dated). The tables are in `results/summary/v3/` and the figures in
`results/figures/v3/`.

**Methods.** The team (`agentic`), the team with the resolver off (`agentic-no_resolver`, INJECT
only), the team with batching (`agentic-batch`), no research squad (`agentic-no_research`),
single agent (`agentic-single_agent`), Aider (the external agent, a fixed instruction written before
any result) and v1 (`cleansweep`, the Phase 1 pipeline with its gatekeeper). The agents' model is
`qwen36-35b-a3b`; the diff audit's is `glm-5-3`.

**Limits.** 120 minutes and 400 LLM requests per run for every method. A run that hits either is
timed out: it stays in every denominator with nothing removed, and safety is computed on the
finished runs. Three v1 runs went past the cap because v1's LLM client caught the cap as one failed
request (INJECT shinkoku 173 min; REAL run 2's pipecat 191.6 min and hyprwhspr 215.19 min); all
three are recorded as timed out, as pre-registered (Deviation 5).

**Sets.**
- **INJECT:** 10 repositories never used in Phases 1–2, seed 4, with v2's planted slop and two
  traps each (out of sample). 69 of 70 runs; Aider could not start on linopy (its repository map
  crashes before any request; not run, Deviation 7).
- **REAL:** 15 AIDev projects. Half of each project's test modules are held out (seed 4) and run
  only after the cleanup; a held-out test that passed in three baseline runs and fails afterwards
  is a behavior change. Run 1 (90 of 90) feeds the tables and H1; run 2 (90 of 90, Deviation 8)
  enters only the audit.
- **AUTONOMY:** 30 repositories, `cleansweep clean` end to end in the Docker sandbox.

### Hypotheses (as pre-registered, tested at the freeze)

| | Hypothesis | Result | Evidence (`hypotheses.csv`) |
|---|---|---|---|
| H1 | On REAL, the team makes fewer wrong edits than Aider in both tiers, and fewer held-out failures | **not supported** | wrong share, confirmed: team 4/191 vs Aider 4/13 (Fisher p=0.0006); all tiers 13/191 vs 5/13 (p=0.0025); projects with a held-out change: team 4 vs Aider 0 of 10 (McNemar p=0.125) |
| H2 | The resolver lowers the team's wrong edits on INJECT | **not supported** | wrong (all tiers) 3 with vs 3 without over 9 repositories (Wilcoxon p=1.0); confirmed 2 vs 2 |
| H3 | Batching keeps the team's safety at no more than 60% of its requests | **supported** (by a tie) | request ratio 0.406 [0.349, 0.470] over 20 projects; wrong 16 vs 16 (Wilcoxon p=1.0); behavior changes 3 vs 4 (McNemar p=1.0) |
| H4 | AUTONOMY completion is at least 90% (raw) | **supported** | pass 1: 27 of 30 (0.900, Wilson [0.744, 0.965]) |

- **H1** fails on its third part only. The team's wrong-edit shares are far lower than Aider's in
  both tiers, but Aider keeps almost nothing (13 kept code edits on 14 finished runs, 22 lines), so
  it changes no held-out test, while the team changes held-out behavior on 4 of 10 paired projects.
- **H2** has no power here. On 9 of the 10 INJECT repositories, the team's and the resolver-off
  arm's final diffs are byte-identical: the resolver changed no decision there, and the shared
  reply cache made the two arms replay the same run. The tenth, gpt4free, timed out in both arms
  and is excluded. So "3 vs 3" is one run counted twice; it does not show that the resolver has
  no effect.
- **H3** is supported at exactly the pre-registered rule, but the wrong-edit totals tie (16 vs 16),
  so a single project could flip it; we report it as supported by a tie. The test pairs the 20
  projects where both arms finished: on 9 INJECT repositories, 4 for batching and 3 for the team;
  on 11 REAL projects, 12 and 13. The audit table's 48 wrong REAL edits for batching are those
  12 plus 36 on openbench. There the team's run used its whole request budget (timed out), so the
  pair is excluded, while batching finished with 36 wrong edits, 33 of them deleted abstract
  `placeholder_ground_truth` overrides. Batching stays off by default.
- **H4** is at the threshold. vllm's first pass-1 run timed out on battery and was rerun on AC under
  a rule written before the timeout (Deviation 2); with the battery run the rate is 26/30 = 0.867.
  Pass 2 after the fixes (v2.1.2) completed all 3 of pass 1's failures (in-sample).

### INJECT (seed 4, out of sample)

| Method | Finished / timed out | Recall [95% CI] | Traps removed | Hidden test changed | Requests (mean) |
|---|---|---|---|---|---|
| Team | 9 / 1 | 0.721 [0.544, 0.833] | 0 | 0 | 152.1 |
| Team, resolver off | 9 / 1 | 0.721 [0.544, 0.833] | 0 | 0 | 150.8 |
| Team, batching | 9 / 1 | 0.721 [0.544, 0.833] | 0 | 0 | 66.0 |
| No research squad | 10 / 0 | 0.794 [0.754, 0.836] | 0 | 0 | 10.7 |
| Single agent | 10 / 0 | 0.529 [0.414, 0.636] | 3 | 3 | 83.0 |
| Aider | 9 / 0 (1 not run) | 0.230 [0.067, 0.403] | 4 | 3 | 3.9 |
| v1 | 9 / 1 | 0.471 [0.348, 0.551] | 0 | 0 | 25.8 |

Recall is planted slop removed over planted slop, with timed-out runs at 0. Every team variant and
v1 removed no trap and changed no hidden test. The single agent removed 3 traps and Aider 4, and
each changed the hidden test in 3 repositories.

### REAL (run 1)

| Method | Finished / timed out | Projects with a held-out change | Visible breaks | Lines removed | Requests (mean) |
|---|---|---|---|---|---|
| Team | 11 / 4 | 4 | 0 | 2,213 | 202.9 |
| Team, batching | 13 / 2 | 4 | 0 | 2,306 | 105.3 |
| No research squad | 14 / 1 | 5 | 0 | 3,452 | 10.4 |
| Single agent | 15 / 0 | 8 | 1 | 3,515 | 128.0 |
| Aider | 14 / 1 | 0 | 1 | 22 | 4.5 |
| v1 | 12 / 3 | 4 | 0 | 1,135 | 31.5 |

### The diff audit (two tiers)

Every kept code edit of a finished run is audited blind (the method hidden): `glm-5-3` votes 3
times, and every edit it flags gets a targeted test (the **confirmed** tier) or a reading under the
rubric (the **reading** tier, LLM-judged); on INJECT the injection key settles traps and plants.
By the freeze: 792 checks over 1,931 audited edits (452 wrong, 199 debatable, 141 fine).

| Set | Method | Kept code edits | Wrong, all tiers (share) | Wrong, confirmed (share) |
|---|---|---|---|---|
| INJECT | Team | 227 | 3 (0.013) | 2 (0.009) |
| INJECT | Team, resolver off | 227 | 3 (0.013) | 2 (0.009) |
| INJECT | Team, batching | 229 | 4 (0.017) | 3 (0.013) |
| INJECT | No research squad | 398 | 12 (0.030) | 11 (0.028) |
| INJECT | Single agent | 165 | 37 (0.224) | 36 (0.218) |
| INJECT | Aider | 14 | 10 (0.714) | 9 (0.643) |
| INJECT | v1 | 146 | 32 (0.219) | 19 (0.130) |
| REAL | Team | 191 | 13 (0.068) | 4 (0.021) |
| REAL | Team, batching | 262 | 48 (0.183) | 19 (0.073) |
| REAL | No research squad | 446 | 58 (0.130) | 24 (0.054) |
| REAL | Single agent | 423 | 87 (0.206) | 51 (0.121) |
| REAL | Aider | 13 | 5 (0.385) | 4 (0.308) |
| REAL | v1 | 147 | 47 (0.320) | 20 (0.136) |

"All tiers" includes LLM-judged readings. The intervals and Fisher tests against the team are in
`audit.csv`.

**What the audit missed** (`audit_miss_v3.csv`, estimates): 50 "no"-voted kept edits each from the
team and v1 got a targeted test or a no-test note and a reading. The team: 0 wrong of 50 (miss rate
0, 95% interval [0, 7.1%]). v1: 5 wrong of 50 by test (10.0% [4.4%, 21.4%]), 6 with readings.

### Cost, the second model and the curve

- **Cost** (`cost.csv`): on REAL the team averages 202.9 requests and 25.1 minutes per finished run,
  batching 105.3 and 20.8, no research squad 10.4 and 21.1, v1 31.5 and 56.4, Aider 4.5 and 17.8.
  Compare methods by requests, not tokens. Requests count every agent request, including replies
  replayed from the run clone's shared LLM cache, and the 400-request budget uses the same count.
  Tokens count only requests sent to the model. So the token means are not comparable between
  methods that ran on the same clone: on INJECT the team without the resolver sent mostly the
  team's prompts and reused their replies, with 150.8 requests but 37,920 tokens per run against
  the team's 152.1 and 321,460.
- **Second model** (`second_model.csv`, `deepseek-v4-1-flash` as the agents' model, 5 INJECT + 5
  REAL): the team finished 9 of 10 with no wrong edit in either tier; the single agent mostly stopped
  at once (the endpoint offers it a `generate_image` tool), removing almost nothing.
- **Curve** (`curve.csv`, the first 5 REAL): thorough and adaptive removed 181 lines each with 3
  wrong edits (all tiers, none confirmed), against the team's 167 lines and 1.

### Autonomy

Pass 1: 27 of 30 completed (0.900, Wilson [0.744, 0.965]); verdicts: everything runs 7, not
verified by tests 9, nothing applied 11; 3 other stops; no run was environment-impossible. Pass 2
on v2.1.2: 3 of 3 (in-sample).

### LLM judge panel (Deviation 9)

No human checked any label. In place of the two human raters, three LLM judges from other model
families (`gpt-oss-120b`, `llama4-maverick-17b`, `gemma4-31b-it`) rated the blinded 100-item
packet: 70 diff-audit edits and 30 review-sheet rows, with the 40 items of the two old calibration
sheets among them. They used the same rubric and view, and each voted 3 times
(`judge_panel.csv`, `judge_panel.md`, run on Nov 13 10:37–10:46).

- **Agreement between the judges:** moderate. Fleiss' κ is 0.382 [0.271, 0.494] on the 3 labels
  and 0.477 [0.346, 0.599] on wrong vs not wrong. The three judges had no majority on 13 of 100
  items (scored debatable).
- **Agreement with the recorded labels:** the panel's κ is 0.373 [0.224, 0.516] on 3 labels and
  0.455 [0.269, 0.620] on wrong vs not wrong. On the diff audit's LLM-judged items it is 0.641
  [0.411, 0.843] (wrong vs not wrong, n=52).
- **Against the 18 confirmed verdicts:** the panel is right on 11 (0.611 [0.386, 0.797]), and each
  judge alone also on 11. It calls 9 of 12 confirmed-wrong edits wrong (sensitivity 0.750
  [0.468, 0.911]), but calls none of the 6 confirmed-fine edits fine: 4 wrong and 2 debatable (specificity,
  not wrong, 0.333 [0.097, 0.700]). Four
  of those six delete a file that the SWE-bench agent's own patch created, which the blinded
  view does not show. The judges lean toward "wrong".
- **The reading tier:** the panel agrees with 28 of 40 reading-tier verdicts on 3 labels and 31
  of 40 on wrong vs not wrong. It overturns 12, listed in `judge_panel.md`.
  - It calls wrong 7 edits recorded as fine or debatable; four of those it calls wrong
    unanimously.
  - It calls 2 recorded-wrong edits fine or debatable, 2 recorded-debatable edits fine, and 1
    recorded-fine edit debatable.
  - These are disagreements between LLMs, not corrections: the recorded verdicts stand as
    frozen.

### Limitations

- No human checked the labels. The reading tier is LLM-judged. A panel of three LLM judges agrees
  with the recorded labels at κ = 0.455 (wrong vs not wrong; 0.373 on 3 labels), and is right on
  11 of 18 confirmed verdicts (a targeted test or a rule).
- The audit checks only flagged edits; the miss-rate estimate above bounds what it misses.
- REAL's held-out tests catch only behavior the project's own tests reach.
- One model family runs the agents in the main runs; the second model covers 10 repositories.
- Methods on one clone share its LLM cache at the agents' fixed temperature. Where the resolver
  changes nothing, the resolver-off arm repeats the team's replies, so H2 compares the two with
  the model's answers held fixed rather than as independent samples.
- Batching stays off by default in v3.0 (`core.agents.investigate_batch: on` in
  `configs/base.yaml` turns it on). H3 holds only by a tie that changed with almost every
  project.
