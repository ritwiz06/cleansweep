# Project status

Where the project stands on Nov 13, after the Phase 3 results freeze (12:00, Arizona time). This
is the public summary of Ritik's local plan and decision log. The acceptance checklist with its
evidence is [requirements.md](../requirements.md).

## The three phases

| Phase | Dates | What | State |
|---|---|---|---|
| Phase 1 | Oct 19 – Oct 30 | the pipeline: detect, judge, batch, check every edit with the Guard; tested on SWE-bench and AIDev | done: v1.0 on Oct 30, patches by Oct 31 |
| Phase 2 | Oct 31 – Nov 5 | the team of ten agents (`cleansweep clean`), Studio, the SlopBench benchmark, the blinded diff audit | done: v2.0 on Nov 5, requirements R1–R16 met |
| Phase 3 | Nov 6 – Nov 15 | the pre-registered final evaluation: four hypotheses, new projects, an outside agent (Aider) as baseline | runs finished Nov 9; results frozen Nov 13 at 12:00; v3.0 release planned for Nov 15 |

Nothing is running. Every Phase 3 run finished by Nov 9 at 06:11, and no new run starts unless
one turns out to be spoiled; none is.

## The Phase 3 scorecard

Four hypotheses, written down on Nov 6 before any main run
([preregistration_v3.md](../preregistration_v3.md)). The numbers come from
`results/summary/v3/hypotheses.csv`, the README's "v3 results" section and
[results.md](../results.md).

| | The question | Result | In plain words |
|---|---|---|---|
| H1 | On 15 real projects, is the team safer than Aider? | **not supported** | The team's kept edits were wrong far less often: 4 of 191 against 4 of 13 confirmed by a test or a rule, and 13 against 5 counting LLM-judged readings. But held-out tests changed on 4 of the 10 projects both finished for the team, and on none for Aider, which kept almost nothing (22 lines in 14 runs). |
| H2 | Does the resolver lower the team's wrong edits on the benchmark? | **not supported, and uninformative** | On 9 of the 10 repositories, the team and the team with the resolver off produced byte-identical diffs. The resolver changed no decision there, and the shared reply cache made the two arms replay the same run. The tenth timed out in both. So "3 against 3" is one run counted twice. |
| H3 | Does batching cut requests to 60% or less with the same safety? | **supported, by a tie** | Batching used 41% of the team's requests, with 16 against 16 wrong edits over the 20 projects where both finished. Batching's other 36 wrong edits on real projects are on openbench, where the team's run hit the request budget and so is not paired. Batching stays off by default. |
| H4 | Does `clean` finish on its own on at least 90% of 30 repositories? | **supported at the threshold** | 27 of 30 ran end to end. |

## The honest limits

- **No human checked the labels.** Three LLM judges from other model families agree with the
  recorded labels at κ = 0.455 (wrong vs not wrong), and are right on 11 of 18 verdicts confirmed
  by a test or a rule. Every reading-tier number stays labeled LLM-judged.
- **The team timed out on 4 of 15 real projects.** A timed-out run stays in every denominator
  with nothing removed.
- **Token counts include only requests that missed the shared cache,** so compare methods by
  requests, not tokens.
- **Nine dated deviations** from the pre-registration are listed in
  [preregistration_v3.md](../preregistration_v3.md#deviations).
- The wrong counts are lower bounds: only edits the auditor flags are checked.

## Key decisions

The full list is in Ritik's local decision log; these are the ones to know.

- **Ritik built the first prototype and the critical path alone (Oct 19 – Oct 26),** because no
  other member had joined the repository before the milestones. The areas stay owned by role. See
  [contributions.md](contributions.md).
- **`clean` never writes into the original project.** It works on a copy and hands over a branch.
- **Doubtful items are reported, not applied.** Public names and framework callbacks stay in the
  suggest lane.
- **Models.** The agents use `qwen36-35b-a3b`; the audit and the AIDev hidden tests use a
  different vendor's model, `glm-5-3`, so they stay independent; the second model family is
  `deepseek-v4-1-flash`.
- **The trained ranker is not the default** (AUC 0.61): it predicts "a reviewer asked to remove
  this", not "safe to remove". A negative result.
- **Pre-registration before any main run (Nov 6):** H1–H4, one cap (120 minutes) and one budget
  (400 requests) for every method, timed-out runs kept in the denominators.
- **The conclusion follows the evidence.** Small real-project results "suggest, but don't
  establish"; every safety claim names its tier.
- **Runs that overlap a laptop sleep are rerun,** never reported.

## Deviations, in short

Nine, each dated and explained in [preregistration_v3.md](../preregistration_v3.md#deviations):
runner patches before and during the runs (never the cleanup code); battery runs rerun on power;
three laptop restarts on Nov 6; a check-only rerun replays the first attempt's replies; the
Phase 1 time cap caught as an LLM failure; one operator-stopped run rerun; Aider cannot start on
one repository; REAL run 2 covers all 15 projects; and the three-judge LLM panel replaces two
human raters (Deviation 9). None changes H1–H4.

## What remains

| Item | Who | When |
|---|---|---|
| v3.0 release: requirements checked, fresh-clone rehearsal, archive tarball | Ritik | planned for Nov 15 |
| Setup, offline checks and table reproduction on three more machines | Maninderjit, Badri, Simran | within 2 days of getting access ([tasks.md](tasks.md)) |
| Two timed rehearsals of the talk | everyone | Nov 16 – Nov 20 |
| The presentation (5 minutes, 4 speakers) | everyone | Nov 21 or Nov 28 |
| Final report: section reviews, proofreading, submission | Ritik assembles; each owner reviews | Dec 4 (confirm on Canvas) |
| Individual peer evaluation | each of us | after the presentation |

Every task has an issue and a due date in [tasks.md](tasks.md).
