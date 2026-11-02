# User guide

This is a short version. The full guide, with screenshots of Studio and watch mode, comes with
v2.0 (requirement R11 in [requirements.md](requirements.md)). Studio is described
[below](#studio).

## Install

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
```

For the LLM features, put an OpenAI-compatible endpoint in `.env` (`VOYAGER_API_KEY`,
`VOYAGER_BASE_URL`, `VOYAGER_MODEL`); see the [README](../README.md#quick-start). Without a key,
`--no-llm` runs everything offline: the agents decide by rules.

## Clean a project

```bash
python -m cleansweep clean path/to/project --dry-run     # plan only: writes blueprint.md
python -m cleansweep clean path/to/project               # safe mode
```

The original folder is never changed. `clean` copies the project into a scratch workspace next
to it (`<project>-cleanup-<time>/`, or `--out`), runs its tests three times for a baseline, finds
cleanup candidates, investigates each one, plans work packages, and applies them one at a time,
keeping a package only if the tests and the probes still pass. It ends with a git branch (one
commit per package), the patches, `CLEANUP_REPORT.md`, `blueprint.md`, `PR_DESCRIPTION.md` and
`CHANGELOG_ENTRY.md`. Apply the branch yourself after reading the report.

Options: `--mode safe|thorough`, `--budget llm=150,minutes=60,tests=80`, `--approve-plan`,
`--exclude FOLDER`, `--test-args "..."`, `--no-install`, `--model`, `--quiet`. The full list and
what each does: [agentic_design.md, section 15](agentic_design.md).

## Studio

```bash
cleansweep studio                      # http://127.0.0.1:8765; --port, --runs DIR, --no-browser
```

The first start builds the frontend with npm (node 20 or later); without npm it prints the
commands (`cd app/studio/frontend && npm ci && npm run build`). Studio listens on localhost only.
It reads three folders: its runs folder (`results/raw/studio/`, or `--runs`), `results/` and
`demo/replay/`. Hidden files, `.env` and other secret files are never served, and every text it
sends is passed through the same redactor the agents use. Everything except Launch works
offline; `demo/replay/` ships four agent-team recordings beside v1's (the toy repo, the demo app
with the feature patch, a Manager step-back scenario and the Skill_Seekers case study; see the
README).

- **Runs**: every recorded run (agent-team cleanups, v1 sweeps, watch folders) with its target,
  mode, model and result. Open one in Replay, follow a live one, or send it to Compare.
- **Launch**: clean a project with the agent team (mode, model, budgets, offline, dry run),
  sweep it with a v1 method and judge mode, or watch a git repository (polls, interval, test
  budget). Targets: the toy repo, the demo app, the prepared demo, or any absolute path. The
  runs started in this session are listed with their status, output and a stop button.
- **Live run** and **Replay**: the metrics bar (slop meter, packages done, test runs, probe
  cases, probe coverage, LLM calls and tokens, elapsed time, with gauges against the run's
  budgets); the phase timeline (time per phase, step-backs outlined, the current phase pulsing,
  the Manager's decisions as marks); the agent graph (the Manager between the research and
  development squads; the active agent glows; each message travels from its sender to all its
  recipients; each node shows its steps, LLM calls and time); the message board (every message
  as a hyperedge, filterable by type, agent and text, with links to the cached artifacts); the
  item board (Candidate, Investigating, Safe, Suggest, Dropped, In package, Kept, Rolled back,
  Repaired; a card opens the verdict, its evidence, the investigator's tool calls and the
  lessons it cites); work packages (blueprint.md, each package's diff, tests, the probe table
  before vs. after, coverage, the UI check, the commit, the Fixer's outcome); and the report
  with the whole diff. Replay adds play/pause, step, a 1–50x speed, a scrubber and "Next
  decision"; a click on a decision jumps to it. A v2 run folder from `cleansweep clean` or
  `exp_case_study.py` replays as it is; one without `cache/` shows the diffs from its report.
- **Compare**: two runs side by side (result, edits, lines and files removed, test runs, LLM
  calls and tokens, time, packages, step-backs, verdicts, lessons) and their time per phase.
- **Case studies** (`results/raw/case_studies/`): tests before and after, size, what happened to
  each candidate by category, the diff stats and diff, `CLEANUP_REPORT.md`, and the review sheet
  with the "LLM-reviewer acceptance (independent model, blinded)" decisions, votes and reasons.
  These are an LLM's judgment, not a human review.
- **Watch**: a `cleansweep watch` folder: the commit stream with each decision (clean or wait)
  and its reason, open slop over time with the cleans marked, the test budget used, links to the
  clean runs; and the simulated watch table (`results/summary/v2/watch_replay.csv`).
- **Results**: every table under `results/summary/v1` and `v2` (sortable, with its Markdown
  notes) and every figure.
- **Dashboard (v1)**: the old Streamlit dashboard's pages, with the same data: Saved reports
  (any sweep report saved under `results/`, the runs folder or `demo/replay/`: its numbers,
  slop meter, plan, Guard verdicts with diffs and the command that restores a quarantined
  file), Live sweep and Replay of v1 runs (stages, the Reviewer's plan, Guard checks, diffs,
  hidden checks, the answer-key score, the toy runs), Scheduler, Baselines, Data and Guard.

The theme button switches between light and dark. Studio's own checks run from
`app/studio/frontend`: `npm run build`, `npx vitest run` and `npx playwright test` (Chromium).
Studio replaced the Streamlit dashboard in v2.0; git history keeps the dashboard.
