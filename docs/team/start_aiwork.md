# Start with your AI coding assistant

This page takes you from an empty laptop to working on your tasks, with an AI coding assistant
doing the setup. It is step 3 of [Start here](README.md#five-steps-on-your-own).

## What you need first

- **GitHub access:** accept the invitation to `ritwiz06/cleansweep`, install the GitHub CLI and
  run `gh auth login`.
- **Your own ASU Voyager key** for the LLM ([setup.md](setup.md#your-voyager-key)). Without one
  you can still do everything offline: `--no-llm` for cleanups and Studio Replay for the demo.
- **Access to the Drive folder "CleanSweep – Final" and both Overleaf projects** (the final
  report and the paper draft). The links are in [handoff.md](handoff.md#shared-locations).
- **An AI coding assistant** that can run commands in a terminal: the one named in the team
  message.

## Folder layout

Put things exactly here, so the starter prompt and the scripts find them:

```
~/CleanSweep/cleansweep/           git clone of the repository
~/CleanSweep/handoff/              the Drive folder "CleanSweep – Final"
~/CleanSweep/cleansweep-archive/   only if a task needs the raw results
```

```bash
mkdir -p ~/CleanSweep && cd ~/CleanSweep
gh repo clone ritwiz06/cleansweep
```

Download the Drive folder (Drive hands you a zip), unzip it, and move its contents into
`~/CleanSweep/handoff/`, so that `~/CleanSweep/handoff/README.txt` and
`~/CleanSweep/handoff/archive/` exist. The README says what each folder holds.

The experiment scripts look for the archive at `../cleansweep-archive/` beside the repository
(`scripts/experiments/v1/archive_paths.py` reads `../cleansweep-archive/raw/`), so the folder
must be named `cleansweep-archive` and sit next to `cleansweep/`. The commands below create
exactly that.

## Check and unpack the archive (only if a task needs it)

The tarball is 106 MB; unpacked, it is 2.2 GB in about 30,000 files, with a `MANIFEST.md` that
says what is where. On macOS and Linux:

```bash
brew install zstd        # macOS; on Linux: sudo apt install zstd
cd ~/CleanSweep/handoff/archive &&
  shasum -a 256 -c cleansweep-archive-2026-11-14.tar.zst.sha256    # must print ": OK"
zstd -dc cleansweep-archive-2026-11-14.tar.zst | tar -xf - -C ~/CleanSweep/
```

On Linux without `shasum`, `sha256sum -c cleansweep-archive-2026-11-14.tar.zst.sha256` checks the
same file. The last command creates `~/CleanSweep/cleansweep-archive/`.

## Which tasks need the archive

- **Badri's data check ([D1](tasks.md#d1-rerun-the-offline-data-table-builders)): yes.** The
  data table builders read `aidev_requests.parquet`, `aidev_labels.parquet`,
  `aidev_detection.parquet` and `aidev_full/aidev_filter.csv` from `data/processed/`, and only the
  archive has them, under `aidev/data_processed/`. After unpacking, copy them in from the
  repository folder:

  ```bash
  cd ~/CleanSweep/cleansweep
  mkdir -p data/processed
  cp -R ~/CleanSweep/cleansweep-archive/aidev/data_processed/{aidev_requests.parquet,aidev_labels.parquet,aidev_detection.parquet,aidev_full} data/processed/
  ```

  Git ignores `data/`; never commit these files, because they hold third-party review comments.
  Checked on Nov 14: the builders' sources read exactly these four, and the tarball holds them.
- **Simran's table check ([E1](tasks.md#e1-reproduce-the-tables-and-check-hypothesescsv),
  `reproduce_tables.sh`): no.** It rebuilds the tables from the committed per-run CSVs. Checked
  on Nov 14: a fresh clone with no archive beside it rebuilt every table, and `git status
  results/` stayed empty.
- **Everything else** (setup, the tests, Studio, the section reviews, the talk): no.

## The starter prompt

Open your AI coding assistant in `~/CleanSweep/cleansweep` and paste this, with your name and role
filled in:

```
I'm <Your Name> (<your role>) on CleanSweep, CSE 572 Group 30. The repo is at
~/CleanSweep/cleansweep and the Drive folder at ~/CleanSweep/handoff.
1. Read docs/team/handoff.md, start_aiwork.md, setup.md, tasks.md,
   contributing.md and presentation.md.
2. Set me up following setup.md: Python 3.11 venv, dependencies, Docker, Node 20
   for Studio, and the pre-push checks (scripts/tools/install_hooks.sh).
   - For the LLM, I'll give you my own Voyager key to put in .env. Never print it,
     and never commit .env.
   - If I have no key, set me up to work offline (--no-llm, Studio Replay).
3. Check the setup: run the offline tests, then open Studio and replay the demo
   app's recording. Tell me what works and what doesn't. File every real problem
   as a GitHub issue labeled "team".
4. List my tasks (`gh issue list --label team --assignee @me`, and my name in
   tasks.md). Unpack the archive into ~/CleanSweep/cleansweep-archive only if a
   task needs it, using the commands in start_aiwork.md.
5. Do my tasks one at a time: one branch and one PR per task, following
   contributing.md, with the pre-push checks passing. Don't change src/ or
   results/ unless the task says so. Never push to main. Never commit data or
   .env. Ask me before deleting anything.
6. When a task is done:
   - add a row to docs/team/contributions.md in the same PR, describing what I
     actually did, with the link
   - comment on the issue, and close it
   - tick my items in the "Handoff checklist" issue (#223)
7. Report and slides: my section review and edits go in Overleaf, not the repo.
   My talk part and its timing are in presentation.md.
Start with step 1, and tell me the plan before changing anything.
```
