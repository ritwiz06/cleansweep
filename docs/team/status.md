# Project status

Where the project stands on Nov 13, after the results freeze at 12:00 (Arizona time). This is
the public summary of Ritik's local plan, handoff notes and decision log. The acceptance
checklist with its evidence is [requirements.md](../requirements.md).

## Timeline

| When | What | Status |
|---|---|---|
| Oct 19 – Oct 30 | **Phase 1**: the pipeline (Reviewer, Guard with differential probes, Scheduler), SWE-bench and AIDev evaluation | done: v1.0 on Oct 30, patch releases v1.0.1 to v1.0.3 by Oct 31 |
| Oct 31 – Nov 5 | **Phase 2**: the agent team (`cleansweep clean`), Studio, the slop-injection benchmark, ablations, the blinded diff audit | done: v2.0 on Nov 5 (planned for Nov 9), requirements R1–R16 met |
| Nov 6 | Phase 3 build: the resolver, batching, autonomy, the Docker sandbox, the Aider baseline, Studio's new screens | done: v2.1 |
| Nov 6 | Phase 3 pre-registration and run rules, committed before any main run | done: v2.1.1 (the code every main run used) |
| Nov 6 – Nov 9 | **Phase 3** runs | done: the last run ended on Nov 9 at 06:11 |
| Nov 7 | fixes after AUTONOMY pass 1 | done: v2.1.2 |
| **Nov 13, 12:00** | **results freeze**: final audit pass, tables, figures, H1–H4, the LLM judge panel | done: [results at the freeze](#results-at-the-freeze) |
| Nov 14 | final report and slides | open |
| Nov 15 | v3.0 release: every requirement checked, a fresh-clone rehearsal, the archive | open |
| Nov 16 – Nov 20 | two timed rehearsals of the talk | open |
| Nov 21 or Nov 28 | the presentation (5 minutes, 4 speakers) | open |

## What is running

Nothing. Every Phase 3 run finished by Nov 9 at 06:11, two days before the last allowed finish
(Nov 13, 06:00). No new runs start unless a run turns out to be spoiled; none is.

## Phase 3 runs

| Set | Planned | Done |
|---|---|---|
| INJECT | 10 repositories × 7 methods, seed 4 | 69 of 70 (Aider cannot start on one repository; Deviation 7) |
| REAL, run 1 | 15 repositories × 6 methods | 90 of 90 |
| REAL, run 2 | 15 × 6 (all 15, since there was slack; Deviation 8) | 90 of 90 |
| Second model | (5 INJECT + 5 REAL) × 2 methods | 20 of 20 |
| Curve (thorough and adaptive) | 5 REAL × 2 | 10 of 10 |
| AUTONOMY pass 1 | 30 repositories | all 30 ran; the completion rate is H4, reported at the freeze |
| AUTONOMY pass 2 | pass 1's failures, after the v2.1.2 fixes | done (in-sample; never replaces pass 1) |
| Audit-miss estimate | 100 more "no"-voted edits from Phase 2, and 100 from Phase 3's run 1 | done; every number from it is an estimate |
| Blinded diff audit | every kept code edit of every Phase 3 run | final: 792 checks, none pending (final pass on Nov 13) |
| LLM judge panel | the 100 blinded items, 3 judges (Deviation 9) | done on Nov 13: 900 votes |

A run that hit the 120-minute cap or the 400-request budget is "timed out": it stays in every
denominator with nothing removed. A run spoiled by sleep, a lost network, a restart or stale
files was rerun, and the spoiled run is not reported.

## What is left

| Item | Who | When |
|---|---|---|
| Final audit pass, tables, figures, H1–H4, the judge panel's numbers, the results pull request | Ritik | done on Nov 13 |
| Reproduce the frozen tables on a second machine | Simran | by Nov 14 |
| Rerun the data table builders on a second machine | Badri | by Nov 14 |
| Fresh-clone install and offline test run on a second machine | Maninderjit | by Nov 14 |
| Final report (Overleaf) and slides; number audit | Ritik, with a section review by each owner | Nov 14 |
| v3.0: requirements R1–R30, fresh-clone rehearsal, release, archive and tarball | Ritik | Nov 15 |
| Upload the new archive tarball to the ASU Drive and check its hash | Ritik | after Nov 15 |
| Two timed rehearsals; the Q&A sheet | everyone | Nov 16 – Nov 20 |

Each task has an issue; see [tasks.md](tasks.md).

## The hypotheses

Stated as pre-registered on Nov 6 ([preregistration_v3.md](../preregistration_v3.md)). All four
were **tested at the freeze, Nov 13 12:00**; the results are in
[Results at the freeze](#results-at-the-freeze) below.

Statistics for all four: bootstrap 95% intervals over projects (10,000 resamples, seed 572);
Wilcoxon signed-rank or exact McNemar where the comparison is paired by project, Fisher's exact
test where it is not; two-sided, alpha 0.05, no correction across the four.

- **H1. On REAL, the team makes fewer wrong edits than Aider, in both tiers, and fewer held-out
  test failures.** Run 1, the finished runs of both. Metrics: the share of kept code edits that
  are wrong, in the confirmed tier and in all tiers, pooled over projects; the number of
  projects with a held-out behavior change. Supported when the team is lower on all three, each
  with p < 0.05 (Fisher's exact test on the two shares, exact McNemar on the projects).
- **H2. The dynamic-reference resolver lowers the team's wrong edits on INJECT seed 4 (out of
  sample).** The team against the team with the resolver off, paired by repository. Metric:
  wrong kept code edits per repository, all tiers. Supported when the resolver has fewer wrong
  edits in total, Wilcoxon p < 0.05, and its confirmed-tier total is not higher.
- **H3. Batching keeps the team's safety at no more than 60% of its LLM requests.** The team
  with batching against the team, on INJECT and REAL run 1, paired by project. Supported when
  the request ratio is at most 0.60, batching has no more wrong edits and no more behavior
  changes in total, and neither paired test shows batching worse at p < 0.05. Batching stays
  off by default unless H3 is supported.
- **H4. AUTONOMY completion is at least 90% (raw rate).** Pass 1, all 30 repositories.
  Completed means a cleanup verdict, no traceback, within the cap; "stopped: <reason>" is valid
  but not completed. Supported when the rate is at least 0.90 (27 of 30), with a Wilson 95%
  interval. Pass 2 and the rate without environment-impossible runs are reported beside it,
  never in its place.

## Results at the freeze

From `results/summary/v3/` (`hypotheses.csv`, `judge_panel.md`); every number and its source is
in the README's "v3 results" section and [results.md](../results.md).

| | Result | Evidence |
|---|---|---|
| H1 | not supported | The team's kept edits are wrong far less often than Aider's (4 of 191 against 4 of 13 confirmed, Fisher p = 0.0006; 13 against 5 in all tiers, p = 0.0025), but the team changed held-out tests on 4 of 10 projects and Aider, which keeps almost nothing, on none (McNemar p = 0.125). |
| H2 | not supported | 3 wrong edits with the resolver and 3 without, over 9 repositories (Wilcoxon p = 1.0). |
| H3 | supported, by a tie | Batching used 41% of the team's requests (95% interval 35–47%) with the same 16 wrong edits; behavior changes 3 with batching, 4 without. |
| H4 | supported | 27 of 30 completed (0.900, Wilson 0.744–0.965), exactly the threshold. |

**The labels.** No human checked them. Three LLM judges from other model families agree with
each other moderately (Fleiss' κ = 0.382) and with the recorded labels at κ = 0.455 (wrong vs not
wrong). They are right on 11 of 18 verdicts confirmed by a test or a rule: 9 of 12 wrong ones, but
none of the 6 fine ones gets "fine". Every reading-tier number stays labeled LLM-judged.

## Phase 3 requirements (R17–R30)

R1–R16 (Phase 2) are met. The Phase 3 checklist:

| R | Requirement | Status |
|---|---|---|
| R17 | dynamic-reference resolver | built; measured by H2 |
| R18 | Docker sandbox | met |
| R19 | autonomy: `clean` finishes on its own | built; judged by H4 at the freeze |
| R20 | investigation batching, measured | built; measured by H3 |
| R21 | Studio: Home, Project view, Before / after | met |
| R22 | Studio: presentation mode, HTML export | met |
| R23 | the INJECT and REAL runs, the audit, the UI check | runs done; tables at the freeze |
| R24 | external baseline (Aider) | built and run; judged by H1 |
| R25 | second model family | runs done (20 of 20); table at the freeze |
| R26 | audit-miss estimate | met |
| R27 | LLM judge panel: agreement, and validity against confirmed verdicts (Deviation 9) | at the freeze |
| R28 | Phase 3 figures | script built; final figures at the freeze |
| R29 | course report and slides with the Phase 3 results | open (Nov 14) |
| R30 | paper draft and v3.0 release | draft started; release Nov 15 |

## Deviations from the pre-registration

Each is dated and explained in [preregistration_v3.md](../preregistration_v3.md#deviations).

1. Runner patches before and during the runs (never the cleanup code itself).
2. Runs on battery: a time-capped run on battery is rerun on power; this rule decides one
   AUTONOMY run, and both numbers are reported.
3. Three laptop restarts on Nov 6; everything that could have run without Docker was rerun.
4. A rerun whose only spoiled part was its check replays its first attempt's LLM replies.
5. The Phase 1 pipeline's time cap was caught as an LLM failure, so its runs could go past the
   cap; such runs count as timed out.
6. One REAL team run was stopped by an operator script and rerun from scratch.
7. Aider cannot start on one INJECT repository; that run is "not run".
8. REAL run 2 covers all 15 projects, not 5.
9. R27 becomes a blinded panel of three LLM judges from other model families (`gpt-oss-120b`,
   `llama4-maverick-17b`, `gemma4-31b-it`): their agreement, and their validity against the
   test-confirmed verdicts. No hypothesis changes, because H1–H4 do not use R27. Consequence:
   the audit's reading tier is LLM-judged.

## Key decisions

Summarized from the decision log, oldest first.

- **The prototype and the critical path came from one account (Oct 19 – Oct 26).** Ritik built a
  runnable prototype across all four areas on day one, so nobody started from an empty
  repository. Because no other member had joined the repository before the milestones, he then
  built the critical path in the other areas too (probes, SWE-bench, AIDev). The areas stay
  owned by their roles. See [contributions.md](contributions.md).
- **The Reviewer moved to the project manager (Oct 19),** to balance the load: the software
  architect's area already held the LLM client, sandboxes, Guard and workflow.
- **Models.** The agents and the judge use `qwen36-35b-a3b`. Hidden tests on AIDev and the
  diff audit use a different vendor's model, `glm-5-3`, so they stay independent. The second
  model family in Phase 3 is `deepseek-v4-1-flash`.
- **The judge never drops an item;** gatekeeper is the default mode, so a doubtful item is
  reported, not applied.
- **Phase 1 defaults (Oct 30):** public names and framework callbacks stay in the suggest lane,
  after AIDev showed deletions of uncalled public functions changing hidden behavior.
- **The trained ranker is not the default** (AUC 0.61): it predicts "a reviewer asked to remove
  this", not "safe to remove". Reported as a negative result.
- **Phase 2 design (Oct 31):** AutoData's manager and squads adapted to cleanup; agents speak a
  JSON ReAct protocol with reasoning off (60 of 60 valid replies in our check); the rules propose
  every step and the LLM may choose only among options the runtime can undo.
- **`clean` never writes into the original project.** It works on a copy and hands over a
  branch; formatting edits are safe only where the project enforces a formatter.
- **Runs that overlap a laptop sleep are rerun, never reported** (Nov 3; applied after each of
  three sleeps in Phase 2).
- **The diff audit's rubric and tiers (Nov 3 – Nov 4):** wrong, debatable, fine; confirmed only
  by a targeted test in the run's own environment, the UI check or a rule; everything else is a
  reading, labeled LLM-judged.
- **The conclusion follows the evidence (Nov 5):** small real-project results "suggest, but don't
  establish"; every safety claim names its tier.
- **Stale files fixed before Phase 3 (Nov 6):** containers hold their own copy of the
  workspace, checked by hash, instead of reading through Docker's file sharing.
- **Pre-registration before any main run (Nov 6):** H1–H4, one cap (120 minutes) and one budget
  (400 requests) for every method, timed-out runs kept in denominators, held-out tests chosen
  by seed, flaky tests left out.
- **Phase 3 repositories (Nov 6):** only repositories whose license allows local use; INJECT and
  REAL take only repositories no earlier phase used; an ordered reserve supplies replacements,
  so none is picked by hand.
- **The progress report in plain language (Nov 9):** Phase 1, 2 and 3 instead of version
  numbers; figures say which direction is better.
- **An LLM judge panel checks the audit's reading tier (Nov 13, Deviation 9),** measured
  against the verdicts that targeted tests confirmed.
