# CleanSweep v3 pre-registration

Written on 2026-11-06, before any INJECT or REAL main run of v3; the commit that adds this file
records its time. Nothing below changes after that commit: any later change is appended under
"Deviations" with its date and reason, and the results report every hypothesis exactly as
written here, as **supported**, **not supported**, or **not run by the freeze**.

v2.0 and v2.1 stay as released; these hypotheses are about the v3 runs only. The code is the
release that adds this file (v2.1.1) or a later patch listed under "Deviations".

## Runs

| Set | Repositories | Methods | Runs |
|---|---|---|---|
| INJECT | the 10 of `data/splits/v3_repos.json` "inject", seed 4 (out of sample: none was used in v1 or v2) | the team (`agentic`, resolver on), the team with the resolver off (`agentic-no_resolver`), the team with batching (`agentic-batch`), no research squad, single agent, Aider, v1 (`cleansweep`, gatekeeper) | 1 each |
| REAL | the 15 of "real" (replacements below), held-out real tests | the team, the team with batching, no research squad, single agent, Aider, v1 | run 1 on all 15; run 2 on the first 5 (on all 15 if the day-1 re-estimate leaves at least 30 hours of slack before 2026-11-13 06:00) |
| Second model | 5 REAL (the first five) and 5 INJECT (the first five) | the team and the single agent with `deepseek-v4-1-flash` as the agents' model | 1 each |
| Curve | the first 5 REAL | thorough (`agentic-thorough`) and adaptive (`agentic-adaptive`) | 1 each |
| AUTONOMY | the 30 of "autonomy" | `cleansweep clean`, the team, safe mode, the Docker sandbox, `--budget minutes=60`, stopped at 75 minutes | pass 1 on all; pass 2 on pass 1's failures after the fixes |

The agents' model is `qwen36-35b-a3b`; the diff audit's model is `glm-5-3` (it differs from both
agent models). Injection plants, checks and the hidden test are v2's (`exp_inject.py`).

## Limits for every method

- One wall-clock cap, **120 minutes**, and one LLM budget, **400 requests** (cache hits are free),
  for every method on INJECT and REAL: the team and its variants, no research squad, the single
  agent, Aider and v1 (`scripts/experiments/v3/methods_v3.py`: `CAP_MINUTES`, `LLM_BUDGET`).
  The team and Aider stop on their own at them; v1 cannot and is stopped at the cap; any run still
  going 5 minutes after the cap is stopped.
- A run that reaches the cap or the budget is **timed out**. It stays in every denominator, with
  yield 0 and "not completed". Safety is computed on the finished runs, and every safety table
  shows both counts (finished and timed out). No run is dropped silently.
- A run spoiled by machine sleep, a lost network or stale files (a failed hash handshake) is rerun
  and the spoiled one is not reported.

## Aider (the external agent)

The fixed instruction `scripts/experiments/v3/prompts/external_cleanup.md` (committed before any
run), the agents' model through the same endpoint, the project's test command as its test command
with auto-test on, the same cap and budget, the same containers and the same checks. Every
adapter intervention is logged per run and reported in the tables: deletions it proposed and that
were carried out, files it emptied that were deleted, files moved aside while it ran.

## Hold-out (REAL)

- Test modules (`test_*.py`, `*_test.py`) are shuffled with seed 4 and the first half is held out;
  `conftest.py` and helpers stay visible. The share of test functions held out is recorded per
  project.
- The whole suite runs 3 times on the base commit. A held-out test counts only if it passes in all
  three; a test whose status changes is flaky, left out of every comparison and counted.
- A project with a single test module, or none of whose held-out tests pass in all three runs, is
  replaced by the next repository of the split's ordered "reserve"; each replacement is listed
  with its reason (`results/raw/real_v3/set.json`). INJECT, if it needs one, takes the reserve
  from the other end.
- A held-out test that passed in all three baseline runs and does not pass after a method's final
  diff is a behavior change; a visible one is a visible break.

## The audit

The blinded diff audit of v2 (`glm-5-3`, 3 votes at temperature 0.3, the majority decides, the
written rubric), on every kept code edit of the v3 runs, never told the method. Every "yes" or
"unsure" is checked: a targeted test in the run's own environment (passes before, fails after:
the **confirmed** tier), the UI check or a rule (confirmed), or a reading (the **reading** tier,
LLM-judged). The injection key's rule (removing planted slop is fine, removing a trap is wrong)
applies to every kept edit on INJECT, flagged or not. The audit-miss estimate adds 50 "no"-voted
edits each for the team and v1 (seed 572) to the 100 of v2, and is repeated on the v3 runs' edits
once they are audited; every number from it is labeled an estimate.

## Hypotheses

Statistics: bootstrap 95% intervals over projects (10,000 resamples, seed 572); Wilcoxon
signed-rank or exact McNemar where the comparison is paired by project, Fisher's exact test where
it is not; all tests two-sided, alpha 0.05, no correction across hypotheses (four hypotheses,
each reported with its p-value).

**H1. On REAL, the team makes fewer wrong edits than Aider, in both tiers, and fewer held-out test
failures.** Run 1, the finished runs of both methods.
- Metrics: the share of kept code edits that are wrong, in the confirmed tier and in all tiers
  (confirmed plus reading), pooled over projects; the number of projects with a held-out behavior
  change.
- Tests: Fisher's exact test on each share (edits pooled); exact McNemar on the projects' held-out
  changes (paired by project).
- Supported when all three hold: the team's share is lower in the confirmed tier with p < 0.05,
  lower in all tiers with p < 0.05, and the team has fewer projects with a held-out change with
  p < 0.05. Otherwise not supported (each part is reported with its direction and p-value).

**H2. The dynamic-reference resolver lowers the team's wrong edits on INJECT seed 4 (out of
sample).** `agentic` against `agentic-no_resolver`, paired by repository.
- Metric: wrong kept code edits per repository, all tiers (confirmed plus reading, the injection
  key's rule included); also reported: the confirmed tier, traps removed, hidden changes, and
  recall (the resolver may lower it).
- Test: Wilcoxon signed-rank on the per-repository counts.
- Supported when the team with the resolver has fewer wrong edits in total, the Wilcoxon p < 0.05,
  and its confirmed-tier total is not higher.

**H3. Batching keeps the team's safety at no more than 60% of its LLM requests.** `agentic-batch`
against `agentic` on INJECT and REAL run 1, paired by project.
- Metrics: the request ratio (batched requests over the team's, summed over the projects both
  finished); safety as wrong kept code edits (all tiers) and hidden or held-out behavior changes.
- Tests: the ratio with a bootstrap 95% interval; Wilcoxon signed-rank on per-project wrong edits;
  exact McNemar on per-project behavior changes.
- Supported when the ratio's point estimate is at most 0.60, batching has no more wrong edits in
  total and no more behavior changes than the team, and neither paired test shows batching worse
  at p < 0.05. Otherwise not supported. The default stays off unless H3 is supported.

**H4. AUTONOMY completion is at least 90% (raw rate).** Pass 1, on all 30 repositories.
- Metric: completed runs (a cleanup verdict, no traceback, within the cap) over 30, with a Wilson
  95% interval. A "stopped: <reason>" verdict is valid but not completed.
- Supported when the point estimate is at least 0.90 (27 of 30).
- Also reported, never in place of pass 1: the rate without the environment-impossible runs, and
  pass 2 after the fixes (in-sample: the fixes were made after seeing pass 1). R19 is judged on the
  raw rate.

The environment-impossible categories, fixed now: needs a GPU; needs the network after the
install; needs a native toolchain or a service the image lacks; not a Python project. A run is put
in one only on the evidence of its verdict, its terminal output and its error log
(`scripts/experiments/v3/exp_autonomy.py`, `ENVIRONMENT`).

## Freeze

Results freeze on **2026-11-13 at 12:00** (America/Phoenix). The last run must have finished by
06:00 that day; anything not finished by the freeze is reported as "not run by the freeze", never
estimated. If the day-1 re-estimate does not fit, these knobs apply in this order, each appended as
a deviation: the second model on 3 + 3 repositories; REAL 15 → 12; no second runs on REAL;
AUTONOMY pass 2 limited to the top three failure causes; INJECT 10 → 8. No method or requirement
is dropped.

## Deviations

None yet.
