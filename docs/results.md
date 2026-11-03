# Results

Every result in detail: what was run, the numbers, and where the files are.
[experiments.md](experiments.md) has the commands, code versions and runtimes;
`results/summary/v1/` and `results/summary/v2/` have the CSVs. v1 comes first; [v2: the agent
team](#v2-the-agent-team) is at the end.

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
c68fcdc, SWE-bench at 7237ccc (with the test-status fix, #118), the injection benchmark, its
ablations and probe strength at f84d568 ([experiments.md](experiments.md) has the commands).
Tables: `results/summary/v2/`; `bash scripts/reproduce_tables.sh` rebuilds `eval_table`,
`eval_paired`, `ablations` and `injection_summary` from the per-run CSVs.

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
n = 6).

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
  #124 a debugger call behind a condition is only suggested; the runs above predate it.
- **Cost.** The team makes more, shorter LLM requests (about 1,400 tokens each on the answer keys
  against v1's 5,800) and finishes sooner: its investigations run three at a time, v1's judge
  waits for long answers.

### Slop-injection benchmark

`injection_summary.csv`, seed 1: the toy repository and 9 AIDev repositories (skillport has too
few importable modules to plant in), each with 7 planted items and 2 traps; planted items
removed out of 10 per category.

| category | team | v1 | one-shot |
|---|---|---|---|
| leftover file | 9 | 10 | 1 |
| dead code | 9 | 10 | 1 |
| exact duplicate | 0 | 0 | 1 |
| unused import | 7 | 8 | 1 |
| debug print | 9 | 0 | 1 |
| commented-out code | 9 | 0 | 1 |
| unused dependency | 7 | 10 | 0 |
| **all planted (of 70)** | **50 (0.71)** | 38 (0.54) | 6 (0.09) |
| traps removed (of 20) | 0 | 0 | 2 |
| projects with a hidden change (of 8 that could show one) | 0 | 0 | 1 |

Two flaws of the benchmark itself. On openwebui-extensions it planted two items and a trap in
a template file that is not valid Python (`class {{CLASS_NAME}}:`), so that project's hidden
test cannot import it, and on imgviz the hidden test failed before every method's cleanup:
a hidden change could show on 8 of the 10 projects. And the one-shot baseline, as in v1, sees
only the lines agent pull requests wrote; in the injected AIDev clones that scope was empty,
so its row is the toy repository alone (6 of 7 removed, both traps, the hidden test broken).

The team's 20 misses: all 7 on openwebui-extensions, where the run stopped when an edit met a
template file named `*.py` (`class {{CLASS_NAME}}:`; an edit that raises is skipped since #125,
after these runs); the duplicates on the other 9 targets (neither system's detectors flagged a
planted copy); 2 on CORAL, where the run's 150 LLM requests ran out before the Investigator
decided; 1 on the toy repository, an import the Investigator judged safe whose edit could not be
applied; and 1 on imgviz, where the Investigator refused the planted `tabulate` as imported by
`generate_readme.py`. That file defines a local function named `tabulate` and imports nothing by
that name: the refusal was wrong (its reference search matched the function by name), and v1's
removal was right. v1 has no detector for debug prints or commented-out code.

### Ablations

`ablations.csv`: one part of the team switched off. On the answer keys, 6 runs each (planted
items found of 60, runs with a hidden change, mean LLM requests, median minutes):

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

The single agent changed hidden behavior in 4 of 6 runs, every time by merging the near-duplicate
rounding helper (the trap every visible test passes). On the demo app it also deleted command
functions the app calls by name (all seven in one run, two in each of the others), so its diff
failed visible tests every time, which it reported as "not verified"; on the toy repository it
reported "everything runs" all three times.

On the injected set, one run of each variant on the 10 projects (planted items removed of 70,
traps removed of 20, projects with a hidden change of the 8 where one can show, mean LLM
requests, median minutes):

| variant | removed | traps | hidden | LLM requests | minutes |
|---|---|---|---|---|---|
| team (LLM Manager) | 50/70 | 0/20 | 0/8 | 92.1 | 3.8 |
| rule-based Manager | 50/70 | 0/20 | 0/8 | 87.0 | 1.9 |
| no research squad | 53/70 | 0/20 | 0/8 | 9.8 | 2.1 |
| broadcast messages | 50/70 | 0/20 | 0/8 | 90.8 | 1.9 |
| artifacts inlined | 49/70 | 0/20 | 0/8 | 90.8 | 1.7 |
| no lessons | 47/70 | 0/20 | 0/8 | 93.3 | 3.1 |
| no coverage guidance | 50/70 | 0/20 | 0/8 | 90.7 | 1.8 |
| single agent | 35/70 | 5/20 | 4/8 | 83.6 | 4.4 |

The team's runs shared the machine with the answer-key and AIDev runs and the ablations mostly
ran alone, so the minutes do not compare across rows. Per project:

- **Single agent.** It deleted the framework callback (`visit_Name`, which `ast.NodeVisitor`
  calls by name) on 5 projects; the hidden test caught it on easy-code-reader, slop-guard,
  Telegram-Snowball-Sampling and dropkit, and on imgviz it failed before the cleanup. It called
  three of those four "everything runs" (slop-guard "not verified"). It removed 2 of the 10
  debug prints and 2 of the 10 commented-out blocks, against the team's 9 each; on
  openwebui-extensions, where the team's run stopped at the template file, it removed 2.
- **No research squad.** 3 more than the team at about a tenth of the requests: on CORAL the
  team's 150 requests ran out before the Investigator decided on the planted import and
  dependency (the variant used 24), and on imgviz the Investigator wrongly kept the planted
  `tabulate` (it took a local function of that name in `generate_readme.py` for an import),
  which this variant removed. Without the squad, v1's
  detectors go straight to the development squad, one package per safe item.
- **Within a few items.** Every variant but no research squad used all 150 requests on CORAL
  and openwebui-extensions, and all but it and the single agent on ai-goofish-monitor; on CORAL the variants differ by one or two
  items (artifacts inlined and no lessons 3, the team 4). No lessons also missed a dependency on
  easy-code-reader and a leftover file on imgviz. No package rolled back in its runs on those
  three projects, so no lesson was missing; with one run each, we read the gap as run-to-run
  variation.

On these benchmarks the one answer the research squad changed by reading the code, the imgviz
`tabulate`, it got wrong; without the squad the team removed at least as much in every category
and no trap. Whether investigation pays off on real projects is
open: no ablation ran there.

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
