# User guide

This is a short version. The full guide, with screenshots of Studio and watch mode, comes with
v2.0.

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

## Dashboard

```bash
streamlit run app/dashboard/dashboard.py
```

It lists the v1 sweep reports under `results/raw/` and has the Live sweep, Scheduler,
Baselines, Data and Guard pages; Replay plays a recorded run offline. Studio replaces it in v2.0.
