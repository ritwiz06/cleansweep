# The presentation

Five minutes, four speakers, nine slides and two backups. Rehearse twice between Nov 16 and
Nov 20 with a timer; the talk is on Nov 21 or Nov 28.

The Phase 3 numbers are final since the results freeze (Nov 13, 12:00). They come from
`results/summary/v3/hypotheses.csv`, the README's "Phase 3 results" section and
[results.md](../results.md).

## Plan

| Time | Speaker | Slide | Content |
|---|---|---|---|
| 0:00 – 0:30 | Ritik | 1. CleanSweep: the problem | agents leave code behind; removing it safely is hard |
| 0:30 – 0:55 | Ritik | 2. Since the progress report | each item the progress report left to do, with its number |
| 0:55 – 1:35 | Ritik | 3. The agent team at work | the live Studio Replay (the clip as fallback): the team, the probes catch `_round_money`, the rollback |
| 1:35 – 2:35 | Badri | 4. Our data | mined review comments, the test projects, SlopBench, the Phase 3 sets |
| 2:35 – 3:15 | Maninderjit | 5. How CleanSweep keeps edits safe | the Manager and ten agents, the Guard, the probes |
| 3:15 – 3:45 | Maninderjit | 6. The audit and its limits | confirmed vs LLM-judged readings; the judge panel |
| 3:45 – 4:05 | Simran | 7. Out of sample | the benchmark on 10 new projects: the team, the single agent, Aider |
| 4:05 – 4:25 | Simran | 8. Real projects with held-out tests | far fewer wrong edits than Aider, but held-out tests changed |
| 4:25 – 5:00 | Simran | 9. Hypotheses scorecard | H1–H4, each with its evidence, and three takeaways |
| after | everyone | 10–11. Backup slides | the Phase 2 benchmark; Studio screenshots if the demo fails |

At a calm pace (130 words a minute) the four scripts below take about five minutes. Read yours
aloud with a timer and cut, rather than speed up. Lines in square brackets are cues, not words to
say.

## Scripts

### Ritik: introduction, progress and demo (slides 1, 2 and 3)

> Hi, we are Group 30, and this is CleanSweep.
>
> Coding agents leave things behind: scratch scripts, old copies of files, duplicate helpers. Removing them by hand is risky. Code that looks dead may still be
> used, for example a method a framework calls by name, and the tests often do not notice.
> CleanSweep removes this leftover code and keeps an edit only if the project still behaves the
> same.
>
> *(slide 2)* Since our progress report, everything it listed as remaining is done. We ran
> Phase 3, the final evaluation we pre-registered on November 6, froze its results on
> November 13, and made the final release on November 14. Each line here is one item and its
> number; Simran comes back to the four hypotheses at the end.
>
> *(slide 3)* [Cue: live Studio Replay. Switch to Studio, already open on Home. Press Try the
> demo, then Next decision until the Guard rolls back _round_money, then Before / after. If
> Studio is not ready, play the clip on this slide.]
>
> This is Studio replaying a cleanup of a small bookstore app. A team of agents finds candidates
> and checks each one. Here it merges a rounding helper into a near-copy, and every test passes.
> But the probes call both versions on the same input: 0.125 rounds to 0.13 before, and to 0.12
> after. So the Guard rolls the edit back, and the other edits are kept. Badri, where does this
> code come from?

### Badri: data (slide 4)

> Our data has three parts.
>
> First, what reviewers ask for: of 6,330 review comments on Python files in AIDev, 535 ask to
> remove code. We clustered them into 15 kinds and mined 64 association rules, which the agents
> use as a knowledge base.
>
> Second, projects to clean: SWE-bench patches written by coding agents, and real AIDev
> repositories. Of 120 we sampled, 21 installed and passed their tests in Docker.
>
> Third, SlopBench, our benchmark: seven kinds of planted slop, two traps that must stay, and a
> hidden test the cleaner never sees.
>
> For Phase 3 we took only new repositories: 10 for the benchmark, 15 real projects with half
> their tests held out, and 30 for a test of autonomy.
>
> Maninderjit will explain how CleanSweep stays safe.

### Maninderjit: safety and the audit (slides 5 and 6)

> CleanSweep always works on a copy and never changes the original project.
>
> A Manager leads ten agents through eight steps: learn the project, run its tests three times,
> find candidates, investigate each one, plan small work packages, then apply and check them
> one at a time. Every rollback becomes a lesson that the next decision must check.
>
> The safety net is the Guard. After each package it runs the tests and differential probes:
> small calls on the code before and after the edit. Any difference rolls the package back, and
> a failing batch is split in half until the bad edit is found.
>
> *(slide 6)* Tests and probes cannot see everything, so an independent model audits every kept
> edit, blind to the method that made it. A test or a rule confirms some verdicts. The rest are
> readings, judged by an LLM, and no human checked them. A panel of three LLM judges agrees with
> the recorded labels at kappa 0.455, and is right on 11 of 18 confirmed verdicts. So we label
> every reading. Simran has the results.

### Simran: results (slides 7, 8 and 9)

> *(slide 7)* On 10 new benchmark projects, the team removed 72 percent of the planted slop and
> no trap. The single agent deleted 3 traps, and Aider 4.
>
> *(slide 8)* On 15 real projects with held-out tests, the team's kept edits were wrong far less
> often than Aider's: 4 of 191 against 4 of 13. But Aider keeps almost nothing, and held-out
> tests changed on 4 of 10 paired projects for the team, against none for Aider.
>
> *(slide 9)* We registered four hypotheses before the runs. H1 is not supported, for that
> reason. H2 is not supported, and tells us nothing: the resolver changed no decision, so both
> arms replayed the same run. H3 holds only by a tie, so batching stays off by default. H4 holds
> at the threshold: 27 of 30 repositories ran end to end.
>
> Three takeaways. Checking every edit makes cleanup much safer. What is left is code used by
> name. And safer per edit is not safer overall. Thank you.

## Transitions

Each speaker ends with the next speaker's name and topic, as in the scripts. Hand over the
clicker with that sentence, not after it. Simran's part has no outgoing line: it ends with
"Thank you". If a speaker runs long, the next one cuts their second paragraph; nobody speeds up.

## Demo plan

The demo is the live Studio Replay on slide 3, cued in the slide's notes; the 36.5 s clip on the
same slide is the fallback. Both show the team, the probes catching `_round_money`, the rollback
and the result. Studio Replay runs offline.

**Before the talk (10 minutes):**

1. The laptop on power, sleep off, notifications off, the screen at 1280×720 or mirrored.
2. Check the clip plays from the deck.
3. Start Studio: in the repository, with the environment active, run `cleansweep studio`. Leave
   it on **Home**; **Try the demo** opens `20261102_demo_feature_agentic`.

**Plan A: the live Studio Replay (the cue in the slide 3 notes).** Switch to Studio, press
**Try the demo**, then **Next decision** (or Space in **Present**) until the `_round_money`
rollback; narrate it with the slide 3 script; then press **Before / after** for the summary card.
Replay calls no LLM and runs no tests, so it works with no network and no key.

**Plan B: the clip on slide 3**, if Studio is not ready. Narrate over it with the same script. It
needs no network.

**Plan C, if neither plays:** the backup slide 11 with the screenshots
`../images/studio/present.png` and `../images/studio/before_after_diff.png`. Say the same words.

## Q&A sheet

Short answers, then where the number comes from. Answer in one or two sentences, then stop. The
owner of each question is in [tasks.md](tasks.md#a2-everyone-prepare-the-qa).

| # | Question | Short answer | Source |
|---|---|---|---|
| 1 | Why not just trust the project's tests? | Tests cover only what they test. The near-duplicate in the demo passes every test, and the audit found wrong team edits that no test, probe or hidden test caught. | README "Known limitations" |
| 2 | What is a hidden (held-out) test? | A test the cleaner never sees, run before and after the cleanup; if its result changes, the cleanup changed behavior. On real projects, half of the project's own test modules are held out. | [tour.md](tour.md#hidden-tests) |
| 3 | How do the probes work? | The LLM writes small calls with edge cases for each changed function; we run them on the code before and after and compare. Any difference rolls the edit back. | [architecture.md](../architecture.md) |
| 4 | Why a team instead of one agent? | One agent that checks its own edits is less safe. Out of sample, the single agent deleted 3 traps and changed the hidden test in 3 of 10 repositories; the team deleted no trap and changed none. In Phase 2 it was 16 of 30 runs against 0 of 30. | [results.md](../results.md) |
| 5 | Does the research squad matter? | On the benchmark it costs requests without adding recall. On five real projects, 0 of the team's 14 kept code edits were wrong, against 4 of 20 without the squad (p = 0.13): it suggests, but does not establish, that it helps. | [results.md](../results.md#real-project-ablation) |
| 6 | How do you decide an edit is wrong? | A written rubric: wrong if something in the project or its users can trigger the change. Confirmed by a targeted test, the UI check or a rule where possible; otherwise a reading, labeled LLM-judged. | [tour.md](tour.md#the-blinded-diff-audit-and-its-two-tiers) |
| 7 | How reliable are the LLM-judged labels? | Only moderately. No human checked them. Three LLM judges from other model families agree with the recorded labels at κ = 0.455 (wrong vs not wrong), and are right on 11 of 18 verdicts confirmed by a test or a rule: 9 of 12 wrong ones, but none of the 6 fine ones gets "fine". They lean toward "wrong". So every reading-tier number says LLM-judged. | `results/summary/v3/judge_panel.md`; Deviation 9 |
| 8 | Are the wrong counts complete? | No, they are lower bounds: only edits the auditor flags are checked. We tested 50 edits it passed from the team: 0 were wrong (95% interval 0 to 7.1%). | [results.md](../results.md), `audit_miss_v3.csv` |
| 9 | Why pre-register? | So we could not choose hypotheses or thresholds after seeing results. Every later change is a dated deviation; there are nine. | [preregistration_v3.md](../preregistration_v3.md) |
| 10 | Can it break my project? | It never touches the original: it works on a copy and hands you a branch to review. Code you do not own runs in a Docker container with no network. | [user guide](../user_guide.md#clean-a-project) |
| 11 | Which models do you use? | `qwen36-35b-a3b` for the agents; `glm-5-3`, another vendor's model, for the audit and the AIDev hidden tests; `deepseek-v4-1-flash` as the second model family; the judge panel uses three other families. All through ASU's Voyager. | [status.md](status.md#key-decisions) |
| 12 | Is SlopBench realistic? | Its plants are simple and our own: seven kinds of slop and two traps. Its value is that we know the right answer and have a hidden test. Phase 3 reruns it on 10 new projects, and real projects with held-out tests complement it. | [slopbench.md](../slopbench.md) |
| 13 | Where is the data mining? | Clustering of 535 removal requests (15 clusters), 64 association rules, a classifier (the ranker, AUC 0.607: a negative result, off by default), similarity search for near-duplicates, and a replay of slop over commit histories. | [results.md](../results.md#aidev-scheduler-replay-removal-requests-ranker) |
| 14 | Why did held-out tests change on real projects? | The team removes real code (2,213 lines on the 15 real projects, against Aider's 22), and a held-out test fails if it reaches code that was removed or changed. Aider changed almost nothing, so it could not fail. We count projects, not causes. This is the one part of H1 we lost, and it is why we say safer per edit is not safer overall. | `real.csv`; [results.md](../results.md) H1 |
| 15 | Why did the resolver show no effect? | On 9 of the 10 benchmark repositories, the team and the team with the resolver off produced byte-identical diffs: the resolver changed no decision. The shared reply cache made the two arms replay the same run, and the tenth repository timed out in both. So "3 vs 3" is one run counted twice, and H2 is not supported and uninformative. | README "Phase 3 results"; [results.md](../results.md) |
| 16 | How does it compare with an existing coding agent? | Same model, same checks: the team's kept edits were wrong far less often (4 of 191 against 4 of 13, confirmed), but Aider keeps almost nothing (22 lines in 14 runs), so it changed no held-out test while the team changed them on 4 of 10 projects. H1 is not supported. | README "Phase 3 results" |
| 17 | What does it cost? | On real projects the team averages 202.9 requests and 25.1 minutes per finished run; batching 105.3 and 20.8; Aider 4.5 and 17.8. Compare requests, not tokens: token counts include only requests that missed the shared cache. | `cost.csv`; [results.md](../results.md) |
| 18 | What does the team still miss, and where does it fail? | Code that only something outside the tests reaches (a web handler, a build hook, a function used by name). It timed out on 4 of 15 real projects, and 27 of 30 repositories ran end to end (H4 at its threshold). | README "Known limitations" |
| 19 | H3 is "supported": why is batching still off? | It holds only by a tie: 41% of the requests, 16 vs 16 wrong edits where both finished. Batching's other 36 wrong edits on real projects are on openbench, where the team's run hit the request budget, so they are not paired. We did not trust a tie, so batching stays off by default. | [results.md](../results.md) |
| 20 | What would you do next? | Find code that is used by name at run time, since that is most of the remaining wrong edits; judge a cleaner per edit and in total, since Phase 3 shows the two can disagree; have a human check a sample of the labels; release SlopBench. | README "Known limitations" |
