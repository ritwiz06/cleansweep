# Tasks

Every task has a GitHub issue with the labels `team`, a role label (`data`, `software`,
`experiments`, `pm`) and a due-date label. The GitHub usernames below are placeholders until each
of us sends Ritik theirs; then Ritik assigns the issues.

When you finish a task: comment on its issue with what you did and what you found, close it,
and add a row to [contributions.md](contributions.md). Problems you find go into new issues
with the `team` label and your role label; say what you ran, what you expected and what
happened, with your operating system.

| ID | Task | Owner | Due | Issue |
|---|---|---|---|---|
| D1 | [Rerun the data table builders and compare](#d1-rerun-the-data-table-builders-and-compare) | Badri | by Nov 14 | [#201](https://github.com/ritwiz06/cleansweep/issues/201) |
| D2 | [Review the Data section and the SlopBench card](#d2-review-the-data-section-and-the-slopbench-card) | Badri | Nov 14 | [#202](https://github.com/ritwiz06/cleansweep/issues/202) |
| D3 | [Present the Data part](#d3-present-the-data-part) | Badri | Nov 20 | [#203](https://github.com/ritwiz06/cleansweep/issues/203) |
| S1 | [Fresh-clone install and offline test run](#s1-fresh-clone-install-and-offline-test-run) | Maninderjit | by Nov 14 | [#204](https://github.com/ritwiz06/cleansweep/issues/204) |
| S2 | [Review the agents and Guard docs](#s2-review-the-agents-and-guard-docs) | Maninderjit | Nov 15 | [#205](https://github.com/ritwiz06/cleansweep/issues/205) |
| S3 | [Test Studio and file UI bugs](#s3-test-studio-and-file-ui-bugs) | Maninderjit | Nov 15 | [#206](https://github.com/ritwiz06/cleansweep/issues/206) |
| S4 | [Present the Methods part](#s4-present-the-methods-part) | Maninderjit | Nov 20 | [#207](https://github.com/ritwiz06/cleansweep/issues/207) |
| E1 | [Reproduce the frozen tables and check H1–H4](#e1-reproduce-the-frozen-tables-and-check-h1h4) | Simran | Nov 14 | [#208](https://github.com/ritwiz06/cleansweep/issues/208) |
| E2 | [Review the Results section](#e2-review-the-results-section) | Simran | Nov 14 | [#209](https://github.com/ritwiz06/cleansweep/issues/209) |
| E3 | [Present the Results part](#e3-present-the-results-part) | Simran | Nov 20 | [#210](https://github.com/ritwiz06/cleansweep/issues/210) |
| P1 | [Integration and the v3.0 release](#p1-integration-and-the-v30-release) | Ritik | Nov 15 | [#211](https://github.com/ritwiz06/cleansweep/issues/211) |
| P2 | [Assemble the final report](#p2-assemble-the-final-report) | Ritik | Nov 14 | [#212](https://github.com/ritwiz06/cleansweep/issues/212) |
| P3 | [Introduction, demo and slides](#p3-introduction-demo-and-slides) | Ritik | Nov 20 | [#213](https://github.com/ritwiz06/cleansweep/issues/213) |
| A1 | [Everyone: proofread the final report](#a1-everyone-proofread-the-final-report) | all four | Nov 14 | [#214](https://github.com/ritwiz06/cleansweep/issues/214) |
| A2 | [Everyone: prepare the Q&A](#a2-everyone-prepare-the-qa) | all four | Nov 20 | [#215](https://github.com/ritwiz06/cleansweep/issues/215) |
| A3 | [Everyone: two timed rehearsals](#a3-everyone-two-timed-rehearsals) | all four | Nov 20 | [#216](https://github.com/ritwiz06/cleansweep/issues/216) |

## Badri (data architect), `@<badri-github>`

### D1. Rerun the data table builders and compare

Due Nov 12, now **by Nov 14**. Goal: a second machine rebuilds the data tables, and every
difference from the committed files is either explained or filed.

**Get the data** (network needed once; nothing here calls an LLM):

```bash
python scripts/data/data_fetch_patchdiff.py      # PatchDiff, about 0.7 GB
hf download hao-li/AIDev repository.parquet pull_request.parquet --repo-type dataset \
    --revision b8dc67df93e7c11f6f20c84129db7232eb1ec253 --local-dir data/raw/aidev
```

SWE-bench Verified (2 MB) downloads itself the first time a script needs it. The command
`huggingface-cli` in [experiments.md](../experiments.md#getting-the-data) is now called `hf`.
These two downloads were not rerun for this page; the Nov 13 comparison below used Ritik's
copies of the same files.
Ask Ritik for the mined data the builders read: the contents of `aidev/data_processed/` in the
archive tarball, copied into `data/processed/` (`aidev_requests.parquet`, `aidev_labels.parquet`,
`aidev_detection.parquet` and the `aidev_full/` folder). Without `aidev_full/`, the funnel counts
only the repositories in the committed files and will differ. These files hold third-party
review comments: never commit them.

**Run the builders:**

```bash
python scripts/data/data_summary.py                    # swebench_patchdiff, tiers, aidev_funnel
mkdir -p .notes                                        # the next script writes a sheet there
python scripts/data/data_aidev_mine.py report          # aidev_taxonomy, aidev_rules
python scripts/data/data_detection_by_category.py      # detection_by_category
python scripts/experiments/v3/slopbench.py list        # SlopBench's repository list
```

**Run the plant validator** on the toy repository (offline; no Docker). First prepare seeds 1
to 3, which plants the slop and traps and checks each seed's plants against the committed
benchmark table; then validate them:

```bash
python - <<'EOF'
import csv, sys
sys.path.insert(0, "scripts/experiments/v2")
import exp_inject
from cleansweep.core.config import load_config
rows = list(csv.DictReader(open("results/summary/v2/injection.csv")))
for seed in (1, 2, 3):
    plants = exp_inject.prepare("toy", seed, load_config())[2]["plants"]
    mine = sorted((p["category"], p["kind"]) for p in plants)
    table = sorted((r["category"], r["kind"]) for r in rows
                   if r["repo"] == "toy" and r["seed"] == str(seed) and r["method"] == "agentic")
    print(f"seed {seed}: {len(mine)} plants, same as injection.csv: {mine == table}")
EOF
python scripts/experiments/v2/exp_inject.py validate --repos toy --seeds 1 2 3
```

Each seed should print "9 plants, same as injection.csv: True", and each line `validate`
prints must have `"invalid": {}`.

Do not run `exp_inject.py run`: it would rewrite the committed benchmark tables from your local
runs only.

**Compare with the committed tables:**

```bash
git status --short results/
git diff --stat results/
git diff results/data_summary/          # the lines that differ
```

What the same commands gave on Nov 13, on the fresh clone with Ritik's data. Check whether you
see the same, and file each one you see as its own issue (labels `team`, `data`):

- Identical: `aidev_funnel.csv`, `swebench_patchdiff.csv`, `aidev_taxonomy.csv`,
  `slopbench_repos.csv`. The toy plants: 9 per seed, all valid, matching `injection.csv`.
- `tiers.csv` gains a row, `tier2_v2subset,20,9,6,18`: the Phase 2 subset split was added after
  the committed table was built.
- `aidev_rules.csv` and `detection_by_category.csv`: the same content, but rules with equal
  values, and categories with equal counts in the `flagged_as` column, come out in another order.
- `data_aidev_mine.py report` stops with `FileNotFoundError` for `.notes/mining_check.md` unless
  `.notes/` exists, before it writes the taxonomy and rules.

**Clean up:** `git restore results/`, and delete `.notes/mining_check.md` (it holds mined review
comments; never commit it).

**Done when:** every builder has run on your machine, each difference is explained in a comment
on the issue or filed as its own issue, and contributions.md has your row.

### D2. Review the Data section and the SlopBench card

Due **Nov 14**. Read the final report's Data section on Overleaf and
[slopbench.md](../slopbench.md). For every number, find its source
(`results/data_summary/`, `results/summary/v3/slopbench_repos.csv`, `sets.csv`) and check that
it matches. Check that a classmate would follow the text: plain words, Phase 1, 2 and 3, no
unexplained terms. Leave comments on Overleaf; file problems in the data card as an issue, or fix
them in a `data/` pull request.

**Done when:** your comments are on Overleaf, the data card has no open problem, and the issue
says what you checked.

### D3. Present the Data part

Due **Nov 20**. Your slot is slide 3, 1:15 to 2:30. Learn the script in
[presentation.md](presentation.md#badri-data-slide-3), say it aloud with a timer (about
75 seconds), and change the wording until it sounds like you. Check slide 3 with Ritik. Take
the Q&A questions on data (questions 13, 14 and 16).

**Done when:** you have given the part in both rehearsals within 80 seconds.

## Maninderjit (software architect), `@<maninderjit-github>`

### S1. Fresh-clone install and offline test run

Due **by Nov 14**. Goal: someone other than Ritik installs CleanSweep from scratch, and every
problem is filed.

1. Follow [setup.md](setup.md) on your machine from the start, in a new folder (not an old
   clone). Write down how long each step takes.
2. Run, in order: the install, `bash scripts/tools/install_hooks.sh`, the three checks, the
   offline toy cleanup, the pipeline's `plan`, `sweep --hidden` and `show`,
   `bash scripts/reproduce_tables.sh` followed by `git status --short results/`, and Studio with
   a replay of `20261102_demo_feature_agentic`.
3. Try the error paths and the plan-only mode: `cleansweep clean does/not/exist`, an `--out`
   folder that is not empty, and `--dry-run` on the toy repository (with `--no-llm`,
   `--sandbox none` and a new `--out` folder).
4. If Docker runs on your machine: `pytest -q -m docker tests/sandbox/test_container.py`.
5. File every problem as its own issue (labels `team`, `software`): the command, what you
   expected, what happened, your operating system and versions. One known problem to confirm:
   the README's quick start runs `cleansweep clean tests/fixtures/toy_repo --no-llm` without
   `--sandbox none`, which stops when Docker is not running for anyone without a commit in this
   repository ([setup.md](setup.md#run-it-offline) explains why).

**Done when:** a comment on the issue lists each step with its time and result, every problem
is its own issue, and setup.md is fixed by a pull request where it was wrong.

### S2. Review the agents and Guard docs

Due **Nov 15**. Read [agentic_design.md](../agentic_design.md) (sections 4, 5, 11 and 12),
[architecture.md](../architecture.md) (Pipeline, What the Guard checks, Lanes and policies),
and the Phase 2 and Guard sections of [tour.md](tour.md). For each passage that is unclear,
wrong or out of date against the code, file an issue (labels `team`, `software`) quoting it and
proposing better wording. Small fixes can go straight into a `rev/` or `core/` pull request.

**Done when:** the issue lists what you read and links your issues or pull requests.

### S3. Test Studio and file UI bugs

Due **Nov 15**. Studio is being restyled now; start when Ritik comments on the issue that the
restyle is merged (or on Nov 14 at the latest, on `main` as it is). Start Studio
(`cleansweep studio`) and go through every screen, in light and dark, at 1280×720, with the
shipped recordings: Home, Runs, Replay (play, pause, step, speeds, the scrubber, Next decision),
the Project tab, Before / after, presentation mode (Space, the arrow keys, Escape), Export HTML
report (open the file with no server), Compare, Case studies, Watch, Results, Evaluation and
Saved reports. The [user guide](../user_guide.md#studio) says what each screen should do.

File each bug as its own issue (labels `team`, `software`, `bug`) with a screenshot, the screen,
the steps to see it, and your browser and operating system.

**Done when:** every screen is checked in both themes, and the issue lists them with the bugs
you filed.

### S4. Present the Methods part

Due **Nov 20**. Your slot is slides 4 and 5, 2:30 to 3:45. Learn the script in
[presentation.md](presentation.md#maninderjit-methods-slides-4-and-5) and time it at about
75 seconds. Take the Q&A questions on how it works (questions 3, 11, 12 and 17).

**Done when:** you have given the part in both rehearsals within 80 seconds.

## Simran (experiment architect), `@<simran-github>`

### E1. Reproduce the frozen tables and check H1–H4

Due **Nov 14**, after the freeze (Nov 13, 12:00) and after Ritik merges the results pull
request; he will comment on the issue when it is in. Goal: a second machine confirms that the
committed tables rebuild, and that each hypothesis's verdict follows from them by the
pre-registered rule.

1. `git switch main && git pull`, then:

   ```bash
   bash scripts/reproduce_tables.sh
   git status --short results/        # must print nothing
   ```

   If the results pull request names another command for the Phase 3 tables, run it too.
2. Open `results/summary/v3/hypotheses.csv` and the tables it rests on (`audit.csv`,
   `real.csv`, `injection.csv`, `cost.csv` and the AUTONOMY table). For each of H1 to H4, take
   the counts from the tables and redo the test the pre-registration names (Fisher's exact test,
   exact McNemar, Wilcoxon signed-rank, the ratio, the Wilson interval; `scipy.stats` has them),
   then apply the rule in [status.md](status.md#the-hypotheses). Check that you reach the same
   verdict and p-values.
3. Check that the README, the report and the slides state each hypothesis's verdict as the
   table does, with the tier named in every safety claim.
4. File each mismatch as its own issue (labels `team`, `experiments`).

**Done when:** the issue has your four verdicts with the numbers you used, and every mismatch
is filed or explained.

### E2. Review the Results section

Due **Nov 14**. Read the final report's Results section on Overleaf. For every number, find its
source table in `results/summary/` and check that it matches; check that every audit number
says its tier (confirmed, or reading, LLM-judged), that small samples say "suggests" rather than
"shows", and that each figure says which direction is better. Leave comments on Overleaf.

**Done when:** your comments are on Overleaf and the issue says what you checked.

### E3. Present the Results part

Due **Nov 20**. Your slot is slides 6 and 7, 3:45 to 5:00. Learn the script in
[presentation.md](presentation.md#simran-results-slides-6-and-7) and fill in the
**[after the freeze]** sentence from `hypotheses.csv` once E1 is done. Take the Q&A questions on
results (questions 4, 5, 9, 10, 15 and 19).

**Done when:** you have given the part in both rehearsals within 80 seconds.

## Ritik (project manager and UI lead), `@ritwiz06`

### P1. Integration and the v3.0 release

Due **Nov 15**. Merge the results pull request after the freeze and the team's pull requests;
answer the issues the team files; check R1–R30; run the fresh-clone rehearsal; tag v3.0; build,
verify and upload the archive tarball to the ASU Drive.

### P2. Assemble the final report

Due **Nov 14**. Bring the Phase 3 results into the report on Overleaf, run the number audit,
take in the section reviews (D2, E2) and the proofreading (A1), and write the Team Contributions
paragraph from [contributions.md](contributions.md) only.

### P3. Introduction, demo and slides

Due **Nov 20**. The slide deck (slides 1 to 7 and the backup slides), shared with everyone
before the first rehearsal; the introduction and the demo in
[presentation.md](presentation.md#demo-plan), with plan A measured at the first rehearsal.

## Everyone

### A1. Everyone: proofread the final report

Due **Nov 14**. Read the whole report once on Overleaf. Mark anything you could not explain
aloud, any typo, and any number without a source. Comments on Overleaf; say on the issue when
you are done.

### A2. Everyone: prepare the Q&A

Due **Nov 20**. Read the [Q&A sheet](presentation.md#qa-sheet). Each of us takes the questions
on our part (named in D3, S4 and E3; Ritik takes 1, 2, 6, 7, 8, 18 and 20) and practices a
one-sentence answer for each. Add questions you expect to the sheet by pull request.

### A3. Everyone: two timed rehearsals

Between **Nov 16 and Nov 20**. Two full run-throughs with the slides, the demo and a timer, at
least a day apart. Note each speaker's time; the whole talk must fit in 5 minutes. After each,
fix what ran long and update [presentation.md](presentation.md).
