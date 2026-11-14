# Contribution log

One row per finished piece of work: who, when, what, and a link (a pull request, an issue, a
file, or a note for work done outside the repository). Add your row in the same pull request
that finishes the task, or right after it for offline work such as a rehearsal or a report
review.

**The final report's Team Contributions paragraph is written from this log only.** If your work
is not here, it is not in the report, so add it.

## What the record shows so far

As of Nov 13, every commit on `main` (690, merge commits included) and every merged pull request
(#4 to #221) comes from Ritik's account. No other account has a commit, a pull request, a review
or an issue in the repository. The decision log records why:

- On Oct 19, Ritik built a runnable prototype across all four areas, so that nobody would start
  from an empty repository.
- From Oct 25, because no other member had joined the repository before the milestones, Ritik also
  built the critical path in the other areas (the probes, the SWE-bench and AIDev work).

The README's Team section names an owner for each area by role (software, data, experiments).
Owning an area by role is not the same as having done the work in it, and this log credits only
what the record shows. Work under Ritik's account includes code written with a coding assistant
under Ritik's direction; the final report's statement on the use of AI tools covers that.

From here on, each of us adds rows for our own work.

## Phase 1: the pipeline (Oct 19 – Oct 31)

| Person | Date | What | Link |
|---|---|---|---|
| Ritik | Oct 19 | Runnable prototype in every area: skeleton and CI, contracts, LLM client, local workspace, toy repository, detectors, Guard, batching, baselines, dashboard | 14 commits on `main`, from `8db2418` |
| Ritik | Oct 25 – Oct 26 | Reviewer: judge modes, prompt fixes, over-engineering review with test evidence, scratch-file signals | [#4](https://github.com/ritwiz06/cleansweep/pull/4), [#11](https://github.com/ritwiz06/cleansweep/pull/11), [#15](https://github.com/ritwiz06/cleansweep/pull/15), [#19](https://github.com/ritwiz06/cleansweep/pull/19), [#20](https://github.com/ritwiz06/cleansweep/pull/20), [#29](https://github.com/ritwiz06/cleansweep/pull/29) |
| Ritik | Oct 25 | Demo app, demo script, live sweep page with replay, README and report assets | [#6](https://github.com/ritwiz06/cleansweep/pull/6)–[#8](https://github.com/ritwiz06/cleansweep/pull/8), [#13](https://github.com/ritwiz06/cleansweep/pull/13), [#16](https://github.com/ritwiz06/cleansweep/pull/16)–[#18](https://github.com/ritwiz06/cleansweep/pull/18) |
| Ritik | Oct 26 – Oct 28 | Differential probes in the Guard, then probes inside the project's own test setup (software area) | [#21](https://github.com/ritwiz06/cleansweep/pull/21), [#35](https://github.com/ritwiz06/cleansweep/pull/35) |
| Ritik | Oct 26 | SWE-bench and PatchDiff loaders and tier splits (data area) | [#22](https://github.com/ritwiz06/cleansweep/pull/22) |
| Ritik | Oct 26 | SWE-bench Docker workspaces, hidden checks, the Tier 1 runner and the one-shot baseline (software and experiments areas) | [#23](https://github.com/ritwiz06/cleansweep/pull/23)–[#25](https://github.com/ritwiz06/cleansweep/pull/25), [#27](https://github.com/ritwiz06/cleansweep/pull/27), [#28](https://github.com/ritwiz06/cleansweep/pull/28) |
| Ritik | Oct 27 – Oct 29 | AIDev: loaders, review-comment mining, removal labels, runnable-repository selection, Docker workspace, agent scope, second-model hidden tests (data and software areas) | [#31](https://github.com/ritwiz06/cleansweep/pull/31), [#32](https://github.com/ritwiz06/cleansweep/pull/32), [#43](https://github.com/ritwiz06/cleansweep/pull/43), [#49](https://github.com/ritwiz06/cleansweep/pull/49), [#50](https://github.com/ritwiz06/cleansweep/pull/50), [#53](https://github.com/ritwiz06/cleansweep/pull/53) |
| Ritik | Oct 27 – Oct 30 | Experiments: Guard strength, statistics and main tables, Scheduler replay, ranker, detection by category, one-shot breakages and variants, Tier 2 final (experiments area) | [#30](https://github.com/ritwiz06/cleansweep/pull/30), [#33](https://github.com/ritwiz06/cleansweep/pull/33), [#34](https://github.com/ritwiz06/cleansweep/pull/34), [#36](https://github.com/ritwiz06/cleansweep/pull/36)–[#39](https://github.com/ritwiz06/cleansweep/pull/39), [#41](https://github.com/ritwiz06/cleansweep/pull/41), [#42](https://github.com/ritwiz06/cleansweep/pull/42), [#45](https://github.com/ritwiz06/cleansweep/pull/45), [#51](https://github.com/ritwiz06/cleansweep/pull/51), [#54](https://github.com/ritwiz06/cleansweep/pull/54) |
| Ritik | Oct 28 – Oct 30 | Hardening and policies: LLM retries, install files out of diffs, public-API and framework-callback policies, dependency check, formatting by the project's ruff settings, self-sweep | [#44](https://github.com/ritwiz06/cleansweep/pull/44), [#46](https://github.com/ritwiz06/cleansweep/pull/46)–[#48](https://github.com/ritwiz06/cleansweep/pull/48), [#52](https://github.com/ritwiz06/cleansweep/pull/52), [#55](https://github.com/ritwiz06/cleansweep/pull/55)–[#63](https://github.com/ritwiz06/cleansweep/pull/63), [#66](https://github.com/ritwiz06/cleansweep/pull/66) |
| Ritik | Oct 28 – Oct 31 | Dashboard pages, AIDev final tables, public docs and `reproduce_tables.sh`, v1.0 and patch releases | [#40](https://github.com/ritwiz06/cleansweep/pull/40), [#64](https://github.com/ritwiz06/cleansweep/pull/64), [#65](https://github.com/ritwiz06/cleansweep/pull/65), [#67](https://github.com/ritwiz06/cleansweep/pull/67)–[#71](https://github.com/ritwiz06/cleansweep/pull/71) |
| Ritik | Oct 25 – Oct 31 | Phase 1 final report, slides and demo clip | offline: report sources on Overleaf |

## Phase 2: the agent team (Oct 31 – Nov 5)

| Person | Date | What | Link |
|---|---|---|---|
| Ritik | Oct 31 – Nov 1 | Agent team: design, runtime, the ten agents, line-level detectors, coverage-guided probes, the LLM-guided Manager, thorough mode | [#72](https://github.com/ritwiz06/cleansweep/pull/72)–[#80](https://github.com/ritwiz06/cleansweep/pull/80), [#88](https://github.com/ritwiz06/cleansweep/pull/88)–[#91](https://github.com/ritwiz06/cleansweep/pull/91), [#93](https://github.com/ritwiz06/cleansweep/pull/93) |
| Ritik | Nov 1 | Repository restructure, layout docs, Phase 2 requirements checklist | [#81](https://github.com/ritwiz06/cleansweep/pull/81)–[#87](https://github.com/ritwiz06/cleansweep/pull/87) |
| Ritik | Nov 1 – Nov 2 | Case studies, review sheets, the UI check, Manager scenarios, watch mode | [#92](https://github.com/ritwiz06/cleansweep/pull/92), [#94](https://github.com/ritwiz06/cleansweep/pull/94)–[#101](https://github.com/ritwiz06/cleansweep/pull/101), [#103](https://github.com/ritwiz06/cleansweep/pull/103), [#105](https://github.com/ritwiz06/cleansweep/pull/105), [#106](https://github.com/ritwiz06/cleansweep/pull/106) |
| Ritik | Nov 2 – Nov 5 | Studio, its recordings and Evaluation screen; the dashboard removed; the user guide | [#111](https://github.com/ritwiz06/cleansweep/pull/111), [#115](https://github.com/ritwiz06/cleansweep/pull/115), [#117](https://github.com/ritwiz06/cleansweep/pull/117), [#119](https://github.com/ritwiz06/cleansweep/pull/119)–[#121](https://github.com/ritwiz06/cleansweep/pull/121), [#123](https://github.com/ritwiz06/cleansweep/pull/123), [#144](https://github.com/ritwiz06/cleansweep/pull/144), [#148](https://github.com/ritwiz06/cleansweep/pull/148), [#152](https://github.com/ritwiz06/cleansweep/pull/152) |
| Ritik | Nov 2 – Nov 5 | Evaluation: SlopBench, the ablations, probe strength, detection, the Phase 2 tables, the blinded diff audit, the real-project ablation, the framework rule re-scored, adaptive investigation | [#104](https://github.com/ritwiz06/cleansweep/pull/104), [#107](https://github.com/ritwiz06/cleansweep/pull/107), [#109](https://github.com/ritwiz06/cleansweep/pull/109), [#110](https://github.com/ritwiz06/cleansweep/pull/110), [#102](https://github.com/ritwiz06/cleansweep/pull/102), [#112](https://github.com/ritwiz06/cleansweep/pull/112), [#114](https://github.com/ritwiz06/cleansweep/pull/114), [#126](https://github.com/ritwiz06/cleansweep/pull/126), [#128](https://github.com/ritwiz06/cleansweep/pull/128), [#129](https://github.com/ritwiz06/cleansweep/pull/129), [#131](https://github.com/ritwiz06/cleansweep/pull/131)–[#140](https://github.com/ritwiz06/cleansweep/pull/140), [#143](https://github.com/ritwiz06/cleansweep/pull/143), [#145](https://github.com/ritwiz06/cleansweep/pull/145)–[#147](https://github.com/ritwiz06/cleansweep/pull/147), [#149](https://github.com/ritwiz06/cleansweep/pull/149)–[#151](https://github.com/ritwiz06/cleansweep/pull/151) |
| Ritik | Nov 2 – Nov 4 | Quality: chaos and property tests, the coverage script, the settings file, run cleanup, housekeeping and the layout check | [#116](https://github.com/ritwiz06/cleansweep/pull/116), [#118](https://github.com/ritwiz06/cleansweep/pull/118), [#122](https://github.com/ritwiz06/cleansweep/pull/122), [#125](https://github.com/ritwiz06/cleansweep/pull/125), [#141](https://github.com/ritwiz06/cleansweep/pull/141), [#142](https://github.com/ritwiz06/cleansweep/pull/142) |
| Ritik | Nov 2 – Nov 5 | Requirements evidence and the v2.0 release | [#108](https://github.com/ritwiz06/cleansweep/pull/108), [#113](https://github.com/ritwiz06/cleansweep/pull/113), [#124](https://github.com/ritwiz06/cleansweep/pull/124), [#127](https://github.com/ritwiz06/cleansweep/pull/127), [#130](https://github.com/ritwiz06/cleansweep/pull/130), [#153](https://github.com/ritwiz06/cleansweep/pull/153) |
| Ritik | Nov 2 – Nov 5 | Phase 2 report and slides, with their number audits | offline: report sources on Overleaf |

## Phase 3: the evaluation (Nov 6 – Nov 15)

| Person | Date | What | Link |
|---|---|---|---|
| Ritik | Nov 6 | Phase 3 build: requirements R17–R30, the resolver, batching, the Aider baseline, the repository set, autonomy, the Docker sandbox, Studio's new screens, the audit-miss estimate, the runners | [#154](https://github.com/ritwiz06/cleansweep/pull/154)–[#166](https://github.com/ritwiz06/cleansweep/pull/166) |
| Ritik | Nov 6 – Nov 7 | The stale-file fix, the pre-registration and run rules, v2.1.1 and v2.1.2 | [#167](https://github.com/ritwiz06/cleansweep/pull/167)–[#169](https://github.com/ritwiz06/cleansweep/pull/169), [#176](https://github.com/ritwiz06/cleansweep/pull/176)–[#178](https://github.com/ritwiz06/cleansweep/pull/178) |
| Ritik | Nov 6 – Nov 13 | Analysis tools, runner fixes, table and figure fixes, Deviations 1–9 | [#170](https://github.com/ritwiz06/cleansweep/pull/170)–[#175](https://github.com/ritwiz06/cleansweep/pull/175), [#179](https://github.com/ritwiz06/cleansweep/pull/179)–[#198](https://github.com/ritwiz06/cleansweep/pull/198) |
| Ritik | Nov 6 – Nov 9 | Every Phase 3 run, and the blinded audit's checks | offline: run logs and audit records; the tables arrive with the results pull request |
| Ritik | Nov 9 | Course progress report (Word and LaTeX), ready to submit | offline: report sources on Overleaf |
| Ritik | Nov 13 | This team pack and the team's task issues | [#200](https://github.com/ritwiz06/cleansweep/pull/200); issues [#201](https://github.com/ritwiz06/cleansweep/issues/201) to [#216](https://github.com/ritwiz06/cleansweep/issues/216) |
| Ritik | Nov 13 | The LLM judge panel in place of the human raters: the blinded 100-item packet, three judges, 900 votes, Fleiss' and Cohen's κ, validity against the confirmed verdicts | [#199](https://github.com/ritwiz06/cleansweep/pull/199) |
| Ritik | Nov 13 | Phase 3 results at the freeze: the final audit pass, tables, figures, H1–H4, the README's v3 results and the results notes on token counts, the shared cache and batching's default | [#217](https://github.com/ritwiz06/cleansweep/pull/217), [#221](https://github.com/ritwiz06/cleansweep/pull/221) |
| Ritik | Nov 13 | Studio design pass: a simpler Home, a first-run tour, presentation-grade screens, accessibility and quality checks, the user guide's screenshots retaken | [#218](https://github.com/ritwiz06/cleansweep/pull/218) |
| Ritik | Nov 13 | The team pack after the freeze, and the README's toy cleanup without Docker | [#219](https://github.com/ritwiz06/cleansweep/pull/219) |
| Ritik | Nov 13 | Requirements R17–R28 with the frozen results as evidence | [#220](https://github.com/ritwiz06/cleansweep/pull/220) |
| Ritik | Nov 14 | Why H2's two arms are identical and what H3's tie pairs, in the results notes and the README | [#224](https://github.com/ritwiz06/cleansweep/pull/224) |
| Ritik | Nov 14 | The team handoff: the handoff page, the handoff meeting, the Q&A, tasks with usernames, and the handoff checklist | [#225](https://github.com/ritwiz06/cleansweep/pull/225); issue [#223](https://github.com/ritwiz06/cleansweep/issues/223) |
| Ritik | Nov 14 | The v3.0 release: requirements R29–R30, the CHANGELOG, the fresh-clone rehearsal, the archive | [#226](https://github.com/ritwiz06/cleansweep/pull/226); issue [#211](https://github.com/ritwiz06/cleansweep/issues/211) |
| Ritik | Nov 13 – Nov 14 | Final report, talk deck and paper draft, with their number audits | offline: report sources on Overleaf |
| Ritik | Nov 14 | The handoff bundle for the Drive folder (submission files, both Overleaf zips, the decision and run logs as PDFs, the archive tarball), and the shared locations and repository control in the handoff page | [#227](https://github.com/ritwiz06/cleansweep/pull/227); offline: the ASU Drive folder |

## Add your rows here

| Person | Date | What | Link |
|---|---|---|---|
