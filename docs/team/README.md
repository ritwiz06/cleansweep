# Start here

**First, read [handoff.md](handoff.md): the state of the project, the owners and the dates, in two pages.**

This folder is for the four of us: Ritik (project manager and UI lead), Badri (data
architect), Maninderjit (software architect) and Simran (experiment architect). It tells you how
to set up, how the system works, where the project stands, and what each of us does until the
presentation.

## What CleanSweep is

Coding agents write code quickly, but they leave things behind: scratch scripts, old copies of
files, duplicate helpers and functions nobody calls. CleanSweep removes that leftover code from a
Python project and keeps an edit only if the project still behaves the same. It works on a copy
of the project: a team of ten agents finds candidates, investigates each one, and applies the
safe ones in small work packages. After every package, the Guard runs the project's tests and
differential probes (the same calls on the code before and after the edit) and rolls back
anything that changed. We test it on agent-written code from SWE-bench and AIDev, on a benchmark
where we plant slop and traps ourselves, and on real projects, with tests the cleaner never sees.

## Where everything lives

| What | Where | Notes |
|---|---|---|
| Code, tests, docs, the committed tables and figures | the GitHub repository `ritwiz06/cleansweep` (private) | every change goes through a pull request ([contributing.md](contributing.md)) |
| The final report's LaTeX sources and figures | the Overleaf project Ritik shares with you | edit there; the report's numbers come from the committed tables |
| The archive tarball (raw run results, LLM caches) and the submission files | the ASU Drive folder Ritik shares with you | Ritik uploads; you read |
| Your `.env` with your own Voyager key | your machine only | never committed, never shared ([setup.md](setup.md#your-voyager-key)) |
| Downloaded data (`data/raw/`, `data/processed/`), run output (`results/raw/`), caches (`.cleansweep/`) | your machine only | git ignores them; raw runs hold third-party code, so they are not published |
| Ritik's working notes (plan, decision log, run log) | Ritik's machine | [status.md](status.md) is their public summary |

## Your first 30 minutes

1. **Install (about 10 minutes).** Follow [setup.md](setup.md) up to "Check the install". You
   need Python 3.11 and git; Docker and a Voyager key are not needed for this path.
2. **Run the offline demo (5 minutes).** Clean the toy repository with the agent team, without an
   LLM:

   ```bash
   cleansweep clean tests/fixtures/toy_repo --no-llm --sandbox none --out ../toy-cleanup
   ```

   It prints each step and ends with "Result: everything runs". Open
   `../toy-cleanup/CLEANUP_REPORT.md` and read what was removed, what was only suggested, and
   why.
3. **Open Studio Replay (10 minutes).** Start Studio with `cleansweep studio` (the first start
   builds the web page, so it needs Node 20). On **Home**, press **Try the demo**, or open
   **Runs** and pick `20261102_demo_feature_agentic`: the agent team cleaning the demo bookstore
   app. The **Project** tab shows each file and function in its state. Press **Next decision**
   until the Guard rolls back `_round_money`, a near-duplicate that every test passes but that
   rounds 0.125 differently. Then press **Before / after** in the header, and **Present** for
   the projector view. Replay calls no LLM and runs no tests, so it works offline.
4. **Read the results (5 minutes).** The README's "v3 results" section (Phase 3, frozen on
   Nov 13 at 12:00); [status.md](status.md) has the scorecard in plain words.

## Then read

- [tour.md](tour.md): the phases, the ten agents, the Guard, the benchmark, the audit, where each
  table comes from, and a glossary.
- [status.md](status.md): the three phases, the scorecard, the limits, what is left.
- [tasks.md](tasks.md): your tasks, each with a due date and a GitHub issue.
- [contributing.md](contributing.md): branches, pull requests and the checks.
- [presentation.md](presentation.md): the 5-minute talk, the script per speaker, the demo plan
  and the Q&A sheet.
- [contributions.md](contributions.md): who did what, from the repository history.
- [meeting_handoff.md](meeting_handoff.md): the agenda for the 30-minute handoff meeting.
