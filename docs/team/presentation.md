# The presentation

The presentation is a video: there is no live slot. Each of us records only our own slides, and
the four parts are joined into one video. Five minutes is a hard stop: eight slides, planned at
4:38 (the target is 4:40). The three backup slides are not recorded.

| When | What |
|---|---|
| Sat Nov 28 | each part uploaded to the Drive folder `recordings/` ([Record your part](#record-your-part)) |
| Tue Dec 1 | the joined video reviewed by all four ([Join the parts](#join-the-parts)) |
| Wed Dec 2 | the video submitted on Canvas |

The Phase 3 numbers are final since the results freeze (Nov 13, 12:00). They come from
`results/summary/v3/hypotheses.csv`, the README's "Phase 3 results" section and
[results.md](../results.md).

## Plan

| Time | Seconds | Speaker | Slide | Content |
|---|---|---|---|---|
| 0:00 – 0:27 | 27 | Ritik | 1. CleanSweep: the problem | agents leave code behind; removing it safely is hard |
| 0:27 – 0:42 | 15 | Ritik | 2. Since the progress report | each item the progress report left to do, with its number |
| 0:42 – 1:19 | 37 | Ritik | 3. The agent team at work | the 36.5 s Studio clip: the team, the probes catch `_round_money`, the rollback |
| 1:19 – 2:04 | 45 | Maninderjit | 4. How CleanSweep keeps edits safe | the Manager, its eight steps, the Guard, the probes |
| 2:04 – 2:28 | 24 | Maninderjit | 5. The audit and its limits | confirmed vs LLM-judged readings; the judge panel |
| 2:28 – 3:32 | 64 | Badri | 6. Our data and the benchmark, out of sample | the mined requests, the projects, SlopBench; 10 new projects: the team, the single agent, Aider |
| 3:32 – 3:55 | 23 | Simran | 7. Real projects with held-out tests | far fewer wrong edits than Aider, but held-out tests changed |
| 3:55 – 4:38 | 43 | Simran | 8. Hypotheses scorecard | H1–H4, each with its evidence, and three takeaways |
| not recorded | – | – | 9–11. Backup slides | our data in full; the Phase 2 benchmark; Studio Replay |

The scripts are 599 words: Ritik 156, Maninderjit 154, Badri 142, Simran 147. At about 135 words a
minute that is the time above. Read yours aloud with a timer and cut, rather than speed up.

## Record your part

Due **Sat Nov 28**. Record only your own slides, within your seconds:

| Speaker | Slides | Seconds | File name |
|---|---|---|---|
| Ritik | 1–3 | 79 | `01_ritik.mp4` |
| Maninderjit | 4–5 | 69 | `04_maninderjit.mp4` |
| Badri | 6 | 64 | `06_badri.mp4` |
| Simran | 7–8 | 66 | `07_simran.mp4` |

1. Download `CSE572_Group30_Slides.pptx` from the Drive folder's `final/`. Save a copy and delete
   every slide but yours.
2. Record it with PowerPoint's **Record Slide Show**, reading your script below. Use a headset or
   a quiet room; turn the camera on only if the course asks for it. Zoom works too: share the
   slide show and record to your computer, which saves an MP4.
3. Start speaking right away and stop the recording after your last word: the parts are joined as
   they are, with nothing trimmed.
4. Export an MP4 (PowerPoint: File > Export, or Create a Video on Windows, with the recorded
   timings and narration). Watch it once: your voice is clear, every slide shows, and it lasts
   no longer than your seconds.
5. Name it as in the table (`NN` is your first slide) and upload it to the Drive folder
   `CleanSweep – Final/recordings/`.

## Join the parts

Ritik (backup: Simran), after Nov 28. Download the Drive folder `recordings/` (for example into
`~/CleanSweep/handoff/recordings/`), then, from the repository:

```bash
bash scripts/tools/stitch_talk.sh ~/CleanSweep/handoff/recordings
```

It joins the `NN_name.mp4` files in slide order, makes each part 1920×1080 at 30 fps, and
normalizes each part's loudness (to -16 LUFS), so that the four voices sound equally loud. It
prints each part's length and writes `talk_final.mp4` into the same folder. If the parts total
more than 4:50, it stops without writing anything: the part that runs past its seconds is
recorded again. The 12 seconds between 4:38 and 4:50 are for the pauses at the ends of the parts.
It needs ffmpeg (`brew install ffmpeg`, or `sudo apt install ffmpeg`).

Upload `talk_final.mp4` to `recordings/`. All four watch it by **Tue Dec 1** and comment on
[#230](https://github.com/ritwiz06/cleansweep/issues/230) that it is fine, or what to fix. Ritik
(backup: Simran) submits it on Canvas by **Wed Dec 2**.

## Scripts

### Ritik: introduction, progress and demo (slides 1, 2 and 3)

Timing: slide 1, 27 s · slide 2, 15 s · slide 3, 37 s = 79 s. The clip is 36.5 s; talk over it.

> Hi, we are Group 30, and this is CleanSweep.
>
> Coding agents leave things behind: scratch scripts, old copies of files, duplicate helpers.
> Removing them is risky, because code that looks dead may still be called by name, and the
> tests do not notice. CleanSweep removes this code and keeps an edit only if the project still
> behaves the same.
>
> *(slide 2)* Since our progress report we finished Phase 3, the final evaluation we
> pre-registered on November 6, and froze its results on November 13. Each line here is one item
> and its number.
>
> *(slide 3)* This is Studio replaying a cleanup of a bookstore app. A team of agents finds
> candidates and checks each one. It merges a rounding helper into a near-copy, and every test
> passes. But the probes call both versions on the same input: 0.125 rounds to 0.13 before and
> to 0.12 after. So the Guard rolls the edit back and keeps the others. Maninderjit explains
> how.

### Maninderjit: safety and the audit (slides 4 and 5)

Timing: slide 4, 45 s · slide 5, 24 s = 69 s.

> CleanSweep works on a copy and never changes the original project. A Manager leads ten agents
> through eight steps: learn the project, run its tests three times, find candidates,
> investigate each one, plan small work packages, then apply and check them one at a time. The
> agents that propose an edit never approve it.
>
> The safety net is the Guard. After each package it runs the tests and differential probes: the
> same calls on the code before and after the edit. Any difference rolls the package back, and a
> failing batch is split in half until the bad edit is found.
>
> *(slide 5)* Tests and probes cannot see everything, so a different model audits every kept
> edit, blind to the method. A test or a rule confirms some verdicts; the rest are readings,
> judged by an LLM. Three LLM judges agree with the labels at kappa 0.455, so we label every
> reading. Badri has the benchmark.

### Badri: data and the benchmark (slide 6)

Timing: slide 6, 64 s = 64 s.

> Our data has three parts. We mined 535 requests to remove code from 6,330 review comments on
> agent-written Python, clustered them into 15 kinds and mined 64 association rules, which the
> agents use as a knowledge base. We clean real projects: patches written by coding agents, and
> AIDev repositories that run in Docker. And we built SlopBench, which plants seven kinds of
> slop into a real project, two traps that look like slop but must stay, and a hidden test the
> cleaner never sees.
>
> For Phase 3 we used only new projects whose license allows it. On 10 new benchmark projects
> the team removed 72 percent of the planted slop, deleted no trap and changed no hidden test.
> The single agent, which has the same tools but checks its own edits, deleted 3 traps, and
> Aider 4. Simran has the real projects.

### Simran: results (slides 7 and 8)

Timing: slide 7, 23 s · slide 8, 43 s = 66 s.

> On 15 real projects with half of their tests held out, the team's kept edits were wrong far
> less often than Aider's: 4 of 191 against 4 of 13. But Aider keeps almost nothing, and
> held-out tests changed on 4 of 10 paired projects for the team, against none for Aider.
>
> *(slide 8)* We registered four hypotheses before the runs. H1 is not supported, for that
> reason. H2 is not supported and tells us nothing: the resolver changed no decision, so both
> versions replayed the same run. H3 holds only by a tie: 41 percent of the requests with the
> same wrong edits, so batching stays off by default. H4 holds at the threshold: 27 of 30
> repositories ran end to end.
>
> Three takeaways. Checking every edit makes cleanup much safer. What is left is code used by
> name. And safer per edit is not safer overall. Thank you.

## Transitions

Each speaker ends with the next speaker's name and topic, as in the scripts, so that the joined
video flows from one part to the next. Simran's part has no outgoing line: it ends with "Thank
you". If your part runs long, cut a sentence and record it again; never speed up.

## Demo plan

The demo is the 36.5 s clip on slide 3, in Ritik's part. It shows the team, the probes catching
`_round_money`, the rollback and the result. Slide 3 lasts 37 s, so talk over the clip with the
slide 3 script.

**Plan A: the clip in the slide show recording.** Start the clip on slide 3 (click it if it does
not start by itself), and check in the exported MP4 that it plays.

**Plan B: if the export does not show the clip,** record slides 1–3 in Zoom instead (share the
slide show and record to your computer), so that the recording shows the clip as it plays.

## Q&A sheet

Short answers, then where the number comes from. Answer in one or two sentences, then stop. A
recorded talk has no live Q&A: the sheet is for questions the TAs may ask about the video or the
report. The owner of each question is in [tasks.md](tasks.md#a2-everyone-prepare-the-qa).

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
| 21 | Where do the test projects come from? | Three kinds: SWE-bench patches written by coding agents, with their own tests; real AIDev repositories (of 666 qualifying Python repositories we sampled 120, and 21 installed and passed their tests in Docker); and SlopBench, our benchmark with planted slop, traps and a hidden test. Phase 3 used only new repositories whose license allows it: 10 for the benchmark, 15 real projects, 30 for autonomy. | backup slide 9; [slopbench.md](../slopbench.md) |
| 22 | Can we see it live? | Yes, offline: Studio Replay of the demo app, the same run as the clip: Try the demo, Next decision until the Guard rolls back `_round_money`, then Before / after. It needs no network, key or Docker. | [handoff.md](handoff.md#if-something-breaks) |
