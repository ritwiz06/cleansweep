# The presentation

Five minutes, four speakers, about 75 seconds each. Rehearse twice between Nov 16 and Nov 20,
with a timer; the talk is on Nov 21 or Nov 28.

The Phase 3 numbers are final since the results freeze (Nov 13, 12:00); they come from the
README's "v3 results" section and [results.md](../results.md). Phase 2 numbers come from the
README's "v2 results" section.

## Plan

| Time | Speaker | Slide | Content |
|---|---|---|---|
| 0:00 – 0:35 | Ritik | 1. CleanSweep | the problem: agents leave code behind; removing it safely is hard |
| 0:35 – 1:15 | Ritik | 2. Demo | Studio: the team cleans the demo app; the Guard rolls back a near-duplicate |
| 1:15 – 2:30 | Badri | 3. Data | mined review comments, the test projects, SlopBench, the Phase 3 sets |
| 2:30 – 3:10 | Maninderjit | 4. The agent team | the Manager's eight steps, the ten agents, the message board and lessons |
| 3:10 – 3:45 | Maninderjit | 5. The Guard and the audit | tests and differential probes, rollback by halves, the blinded audit |
| 3:45 – 4:20 | Simran | 6. Results: Phase 2 | SlopBench, the single agent, the one-shot cleanup, the audit |
| 4:20 – 5:00 | Simran | 7. Results: Phase 3, and what we learned | H1–H4 (H1 and H2 not supported, H3 and H4 supported); the takeaway |
| after | everyone | 8+. Backup slides | figures and tables for the Q&A |

At a calm pace (130 words a minute), 75 seconds is about 160 words. The scripts below come to
about 630 words, a little under 5 minutes, so the Phase 3 sentence has to replace words in
Simran's part, not add them. Read yours aloud with a timer and cut, rather than speed up.

## Scripts

### Ritik: introduction (slide 1)

> Hi, we are Group 30, and this is CleanSweep.
>
> Coding agents write a lot of code, and they leave things behind: scratch scripts, old copies
> of files, duplicate helpers. Removing them by hand is risky. Code that looks dead may still be
> used, for example a method a framework calls by name, and the tests often do not notice.
>
> CleanSweep removes this leftover code and keeps an edit only if the project still behaves the
> same. Let me show you.

### Ritik: demo (slide 2)

> This is Studio replaying a real cleanup of a small bookstore app that an agent built. The
> Manager walks the team through its steps.
>
> Here the team merges a rounding helper into a near-copy. Every test passes. But the probes
> call both versions on the same inputs: 0.125 rounds to 0.13 before, and to 0.12 after. So the
> Guard rolls it back and writes a lesson.
>
> In the end, five edits are kept and all 12 tests still pass. Badri, where does this code come
> from?

### Badri: data (slide 3)

> Our data has three parts.
>
> First, what reviewers ask for. We mined AIDev: of 6,330 review comments that people wrote on
> Python files, 535 ask to remove code. We clustered them into 15 kinds and mined 64 association
> rules, and the agents use these as a knowledge base.
>
> Second, projects to clean: SWE-bench patches written by coding agents, which come with their
> own tests, and real AIDev repositories. Of 666 qualifying Python repositories we sampled 120,
> and 21 installed and passed their tests in Docker.
>
> Third, a benchmark we built, SlopBench. We plant seven kinds of slop into real projects, plus
> two traps that look like slop but must stay, and a hidden test the cleaner never sees.
>
> For Phase 3 we took only new repositories whose license allows it: 10 for the benchmark,
> 15 real projects with half of their tests held out, and 30 for a test of autonomy.
>
> Maninderjit will explain how CleanSweep cleans them.

### Maninderjit: methods (slides 4 and 5)

> CleanSweep always works on a copy and never changes the original project.
>
> In Phase 1 it was a pipeline: detectors, an LLM judge, and a Guard that checks every edit. In
> Phase 2 we made it a team of ten agents, adapted from AutoData. A Manager walks through eight
> steps: learn the project, run its tests three times, find candidates, investigate each one,
> plan small work packages, then apply and check them one at a time. The agents talk through a
> message board, and every rollback becomes a lesson the next decision must check.
>
> *(slide 5)* The safety net is the Guard. After each package it runs the tests and
> differential probes: small calls on the code before and after the edit. Any difference rolls
> the package back, and a failing batch is split in half until the bad edit is found.
>
> An independent model also audits every kept edit, blind to the method that made it.
>
> Simran has the results.

### Simran: results (slides 6 and 7)

> On SlopBench, the team removed 81 percent of the planted slop and no trap, and no hidden test
> changed in its 30 runs. The single agent changed hidden behavior in 16 of 30 runs; the one-shot
> cleanup in 19 of 20.
>
> Passing tests is not enough: the audit found 18 wrong among the team's 804 kept edits, mostly
> code called by name.
>
> *(slide 7)* Phase 3 tested four hypotheses we registered before the runs. Against Aider on real
> projects, the team's edits were wrong far less often, but Aider keeps almost nothing, so the
> team changed more held-out tests: H1 is not supported. The resolver had no measurable effect.
> Batching used 41 percent of the requests with the same wrong edits. And the tool finished on
> its own on 27 of 30 projects.
>
> What we learned: checking every edit makes cleanup much safer; what remains is code used by
> name, and safer per edit is not safer overall. Thank you.

## Transitions

Each speaker ends with the next speaker's name and topic, as in the scripts. Hand over the
clicker with that sentence, not after it. If a speaker runs long, the next one cuts their
second paragraph; nobody speeds up.

## Demo plan

The demo is 40 seconds, so it shows one moment: the Guard rolling back `_round_money`.

**Before the talk (10 minutes):**

1. The laptop on power, sleep off, notifications off, the screen at 1280×720 or mirrored.
2. `bash demo/prepare_demo.sh --with-feature`, then `cleansweep studio`. Check that **Runs**
   lists `20261102_demo_feature_agentic`.
3. Open that recording, press **Present**, and leave it at the start.
4. For plan A only: `.env` with Ritik's key, and run the live cleanup of the prepared demo app
   once the day before, so the LLM cache is warm.

**Plan A, live (only if both rehearsals worked):** at 0:00, on **Home**, start a cleanup of the
prepared demo app in safe mode, then give the introduction. At 0:35, switch to the live run. The
recorded run took about 2 minutes with a cold cache; measure a warm run at the first rehearsal.
If it has not reached EXECUTE by 0:35, or anything looks wrong, go to plan B at once.

**Plan B, Replay (the safe fallback, and the default):** the recording in presentation mode.
Space jumps to the next decision; press it until the `_round_money` rollback, narrate it, then
open **Before / after** for the summary card. Replay calls no LLM and runs no tests, so it works
with no network.

**If Studio itself fails:** the screenshots `../images/studio/present.png` and
`../images/studio/before_after_diff.png` on a backup slide.

## Q&A sheet

Short answers, then where the number comes from. Answer in one or two sentences, then stop.

| # | Question | Short answer | Source |
|---|---|---|---|
| 1 | Why not just trust the project's tests? | Tests cover only what they test. The near-duplicate in the demo passes every test, and the audit found 18 wrong team edits that no test, probe or hidden test caught. | README "v2 results", diff audit |
| 2 | What is a hidden test? | A test the cleaner never sees, run before and after the cleanup; if its result changes, the cleanup changed behavior. | [tour.md](tour.md#hidden-tests) |
| 3 | How do the probes work? | The LLM writes small calls with edge cases for each changed function; we run them on the code before and after and compare. Any difference rolls the edit back. | [architecture.md](../architecture.md#what-the-guard-checks) |
| 4 | Why a team instead of one agent? | One agent that checks its own edits is not safe: on SlopBench it changed hidden behavior in 16 of 30 runs, the team in 0 of 30. | [results.md](../results.md#slop-injection-benchmark) |
| 5 | Does the research squad matter? | On the benchmark it costs requests without adding recall: without it the team removed 176 planted items against 170. On five real projects, 0 of the team's 14 kept code edits were wrong, against 4 of 20 without the squad (p = 0.13), which suggests but does not establish that it helps. | [results.md](../results.md#real-project-ablation) |
| 6 | How do you decide an edit is wrong? | A written rubric: wrong if something in the project or its users can trigger the change. Confirmed by a targeted test where possible; otherwise a reading, labeled LLM-judged. | [tour.md](tour.md#the-blinded-diff-audit-and-its-two-tiers) |
| 7 | Isn't the reading tier just an LLM's opinion? | Yes, and we label it so. A blinded panel of three LLM judges from other model families agrees with the recorded labels at κ = 0.455 (wrong vs not wrong) and is right on 11 of 18 verdicts confirmed by a test or a rule; it leans toward "wrong" (Deviation 9). No human checked the labels. | [judge_panel.md](../../results/summary/v3/judge_panel.md) |
| 8 | Are the wrong counts complete? | No, they are lower bounds: only edits the auditor flags are checked. We estimate the misses by testing a random sample of the edits it passed. | [experiments.md](../experiments.md#v3-audit-miss-estimate) |
| 9 | What does it cost? | On the answer keys, 41.5 LLM requests per run against 5.5 for Phase 1, but fewer minutes (median 1.7 against 4.8). | README "v2 results" table |
| 10 | What does the team still miss? | Exact duplicates across two modules (0 of 30; rewrites only handle uses in the same file), and a few unused imports and dependencies. | [results.md](../results.md#slop-injection-benchmark) |
| 11 | Can it break my project? | It never touches the original: it works on a copy and hands you a branch to review. Code you do not own runs in a Docker container with no network. | [user guide](../user_guide.md#clean-a-project) |
| 12 | Which models do you use? | `qwen36-35b-a3b` for the agents; `glm-5-3`, another vendor's model, for the audit and the AIDev hidden tests; `deepseek-v4-1-flash` as the second model family in Phase 3; all through ASU's Voyager. | [status.md](status.md#key-decisions) |
| 13 | Is SlopBench realistic? | Its plants are simple and our own: seven kinds of slop and two traps. Its value is that we know the right answer and have a hidden test. Real projects, with held-out tests, complement it. | [slopbench.md](../slopbench.md) |
| 14 | Where is the data mining? | Clustering of 535 removal requests (15 clusters), 64 association rules, a classifier (the ranker), similarity search for near-duplicates, and a replay of slop over commit histories. | [results.md](../results.md#aidev-scheduler-replay-removal-requests-ranker) |
| 15 | How did the classifier do? | Barely better than chance (AUC 0.607): it learns "a reviewer asked to remove this", not "safe to remove", so it is off by default. A negative result. | README "v1 results summary" |
| 16 | When should you sweep a project? | In our replay, a daily sweep cuts slop debt by 87% against never sweeping, at 1.8 times the test runs of sweeping after every agent pull request. | README "v1 results summary" |
| 17 | What does the LLM add to the Manager? | In a budget scenario it stopped at the right time 3 of 3 times, the rules 0 of 3; neither went back after many rollbacks. | [results.md](../results.md#manager-scenarios) |
| 18 | Why pre-register? | So we could not choose hypotheses or thresholds after seeing results. Every later change is a dated deviation. | [preregistration_v3.md](../preregistration_v3.md) |
| 19 | How does it compare with an existing coding agent? | Same model, same checks: the team's kept edits were wrong far less often (4 of 191 against 4 of 13, confirmed), but Aider keeps almost nothing (22 lines), so it changed no held-out test while the team changed them on 4 of 10 projects. H1 is not supported. | README "v3 results" |
| 20 | What would you do next? | Find code that is used by name at run time, since that is most of the remaining wrong edits; judge a cleaner per edit and in total, since Phase 3 shows the two can disagree; more seeds and projects; release SlopBench. | README "Known limitations" |
