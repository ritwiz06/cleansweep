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

Times are America/Phoenix. The cleanup code (`src/`) is v2.1.1's in every main run; only the
experiment runners changed, and AUTONOMY pass 2 uses v2.1.2 as planned (fixes made after pass 1).

1. **Runner patches (2026-11-06 12:47 to 2026-11-07 00:12).** The runs use these commits:
   - #170 (12:47): the analysis tools, and the second-model method labels `agentic-m2` and
     `agentic-single_agent-m2` (the agents' model set to `deepseek-v4-1-flash`, as registered).
   - #171 (13:14): the AUTONOMY runner keeps Git LFS pointer files in its scratch copies, and a
     harness error ends that repository's run as failed instead of ending the sweep. Pass 1 ran
     at this commit (6db8b37).
   - #173 (16:12): INJECT replaces a repository it cannot use (its hidden test fails before any
     cleanup, or it cannot be prepared) with the next one from the reserve's far end, as
     "Hold-out" says; the plant scan skips `.git`, after a background `git gc` crashed one
     prepare. The second-model and curve runs use this commit (e05242b).
   - #175 (2026-11-07 00:12): Aider's input files are copied into AIDev workspaces that run as
     copies. Before it, Aider never started on them. An Aider run that exits non-zero without one
     LLM request is a harness error and is rerun, never scored. The one Aider record made before
     the fix (INJECT python-snap7) is not reported. The INJECT and REAL main runs use this commit
     (13bd11f).
2. **Runs on battery (2026-11-06 15:02).** The runs were started on battery at the project
   manager's request. Low Power Mode slows the CPU, so a run that timed out on battery is rerun on
   AC, and the battery run is not reported. This rule was written before the run it affected timed
   out, and it decides H4: AUTONOMY's vllm run timed out on battery at 16:46 and completed on AC,
   which makes pass 1 27 of 30 = 0.900, exactly the threshold. With the battery run it would be 26 of 30 = 0.867.
   The results report both numbers and judge H4 on the rule.
3. **Restarts (2026-11-06 13:58, 20:05 and 22:05).** The laptop restarted three times, and Docker
   quit before the 20:05 restart. Every run or check that could have run without Docker is
   treated as spoiled ("Limits") and rerun: 87 REAL runs that only logged errors, one held-out
   check, and two interrupted AUTONOMY reruns. Records finished before Docker quit are kept.
4. **Reruns replay the LLM cache (2026-11-07).** A run rerun because only its check was spoiled
   replays its first attempt's cached LLM replies, so its cleanup is the same (its `final.diff` is
   checked to be identical). Its time and LLM requests are the first attempt's.
5. **v1's time cap was caught as an LLM failure (2026-11-07 07:06).** The runner cuts v1 at the
   cap by raising an exception inside the run; v1's LLM client caught it as an ordinary request
   failure and v1 skipped that step, so INJECT shinkoku's v1 run went on to 173 minutes (a second
   signal sent at 07:59 was caught the same way). It counts as timed out by its time, as
   pre-registered: its record says "time cap" and the tables count nothing removed. From #189 the
   cap is not an ordinary error, so nothing in a run can catch it; the running chains keep their
   runner, and another v1 run past the cap would also end late and count as timed out.
6. **REAL pipecat's team run was stopped by an operator script (2026-11-07 10:38).** A script
   meant to move the REAL chain onto a shared project queue after pipecat's v1 run matched an
   old log line and stopped the team's pipecat run after about 113 of its 120 minutes. The run
   is spoiled and rerun from scratch: the REAL clone's LLM cache was put back to its state when
   the run began (the stopped attempt's replies removed), so the rerun replays nothing of it and
   has the same budget as every other run. REAL run 1's remaining projects are taken from that
   queue by two clones at the same commit; which clone runs a project does not change a result.
7. **INJECT linopy's Aider run cannot start (2026-11-07 22:12).** Aider 0.86.2 exits on its
   initial repository scan with a `tree_sitter.QueryError` in its repository map, before any LLM
   request. The rule in 1 (#175) reruns such a harness error; the rerun at 22:14 failed the same
   way. The run is recorded as not run (no record, no recall, no audit), as for a run not made by
   the freeze; Aider's INJECT row covers the other nine repositories. From 22:12 a third clone at
   the same commit (the INJECT clone, after INJECT ended) also takes REAL projects from the queue
   in 6.
