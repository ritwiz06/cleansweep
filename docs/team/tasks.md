# Tasks

Every task has a GitHub issue with the labels `team`, a role label (`data`, `software`,
`experiments`, `pm`) and a due label. Due dates:

- **Setup and checks:** within 2 days of getting access. Today that means **Nov 15**. Badri's
  collaborator invitation is still pending, so his clock starts when he accepts it.
- **Section reviews and proofreading:** before the final report is submitted. Our date is
  **Nov 30**, which leaves four days before Dec 4 (confirm the date on Canvas).
- **Talk parts, Q&A and rehearsals:** before the presentation. Our date is **Nov 20**; the
  rehearsals are Nov 16 – Nov 20, and the talk is on Nov 21 or Nov 28.

When you finish a task: comment on its issue with what you did and what you found, close it, and
add a row to [contributions.md](contributions.md). Problems you find go into new issues with the
`team` label and your role label; say what you ran, what you expected and what happened, with
your operating system. The first thing to do is [meeting_handoff.md](meeting_handoff.md)'s
agenda and the ["Handoff checklist" issue](https://github.com/ritwiz06/cleansweep/issues/223).

| ID | Task | Owner | Due | Issue |
|---|---|---|---|---|
| S1 | [Fresh-clone install and full offline test run](#s1-fresh-clone-install-and-full-offline-test-run) | Maninderjit (`msbhullar`) | Nov 15 | [#204](https://github.com/ritwiz06/cleansweep/issues/204) |
| S3 | [Test Studio and file UI bugs](#s3-test-studio-and-file-ui-bugs) | Maninderjit | Nov 15 | [#206](https://github.com/ritwiz06/cleansweep/issues/206) |
| S2 | [Review the Methods section](#s2-review-the-methods-section) | Maninderjit | Nov 30 | [#205](https://github.com/ritwiz06/cleansweep/issues/205) |
| S4 | [Present the Methods part](#s4-present-the-methods-part) | Maninderjit | Nov 20 | [#207](https://github.com/ritwiz06/cleansweep/issues/207) |
| D1 | [Rerun the offline data table builders](#d1-rerun-the-offline-data-table-builders) | Badri (`byeluri31`) | Nov 15 | [#201](https://github.com/ritwiz06/cleansweep/issues/201) |
| D2 | [Review the Data section and the SlopBench data card](#d2-review-the-data-section-and-the-slopbench-data-card) | Badri | Nov 30 | [#202](https://github.com/ritwiz06/cleansweep/issues/202) |
| D3 | [Present the Data part](#d3-present-the-data-part) | Badri | Nov 20 | [#203](https://github.com/ritwiz06/cleansweep/issues/203) |
| E1 | [Reproduce the tables and check `hypotheses.csv`](#e1-reproduce-the-tables-and-check-hypothesescsv) | Simran (`SIMRANSHARMA2140`) | Nov 15 | [#208](https://github.com/ritwiz06/cleansweep/issues/208) |
| E2 | [Review the Results section](#e2-review-the-results-section) | Simran | Nov 30 | [#209](https://github.com/ritwiz06/cleansweep/issues/209) |
| E3 | [Present the Results part](#e3-present-the-results-part) | Simran | Nov 20 | [#210](https://github.com/ritwiz06/cleansweep/issues/210) |
| P1 | [Integration and the v3.0 release](#p1-integration-and-the-v30-release) | Ritik (`ritwiz06`) | Nov 15 | [#211](https://github.com/ritwiz06/cleansweep/issues/211) |
| P3 | [Introduction, demo and slides](#p3-introduction-demo-and-slides) | Ritik | Nov 20 | [#213](https://github.com/ritwiz06/cleansweep/issues/213) |
| P2 | [Assemble and submit the final report](#p2-assemble-and-submit-the-final-report) | Ritik | Dec 4 | [#212](https://github.com/ritwiz06/cleansweep/issues/212) |
| A1 | [Everyone: proofread the final report](#a1-everyone-proofread-the-final-report) | all four | Nov 30 | [#214](https://github.com/ritwiz06/cleansweep/issues/214) |
| A2 | [Everyone: prepare the Q&A](#a2-everyone-prepare-the-qa) | all four | Nov 20 | [#215](https://github.com/ritwiz06/cleansweep/issues/215) |
| A3 | [Everyone: two timed rehearsals](#a3-everyone-two-timed-rehearsals) | all four | Nov 20 | [#216](https://github.com/ritwiz06/cleansweep/issues/216) |
| A4 | [Everyone: individual peer evaluation](#a4-everyone-individual-peer-evaluation) | each of us | after the talk | [#222](https://github.com/ritwiz06/cleansweep/issues/222) |

## Maninderjit (software architect), `@msbhullar`

### S1. Fresh-clone install and full offline test run

Due **Nov 15**. Goal: someone other than Ritik installs CleanSweep from scratch, and every
problem is filed.

1. Follow [setup.md](setup.md) from the start, in a new folder (not an old clone). Write down
   how long each step takes.
2. Run, in order: the install, `bash scripts/tools/install_hooks.sh`, the three checks, the
   offline toy cleanup, the pipeline's `plan`, `sweep --hidden` and `show`,
   `bash scripts/reproduce_tables.sh` followed by `git status --short results/`, and Studio with
   a replay of `20261102_demo_feature_agentic`.
3. Try the error paths and the plan-only mode: `cleansweep clean does/not/exist`, an `--out`
   folder that is not empty, and `--dry-run` on the toy repository (with `--no-llm`,
   `--sandbox none` and a new `--out` folder).
4. If Docker runs on your machine: `pytest -q -m docker tests/sandbox/test_container.py`.
5. File every problem as its own issue (labels `team`, `software`): the command, what you
   expected, what happened, your operating system and versions.

**Done when:** a comment on the issue lists each step with its time and result, every problem is
its own issue, and setup.md is fixed by a pull request where it was wrong.

### S3. Test Studio and file UI bugs

Due **Nov 15**. Start Studio (`cleansweep studio`) on `main` and go through every screen in light
and dark, at 1280×720, with the shipped recordings: Home (including "Take the tour" and "Try the
demo"), Runs, Launch, Replay (Play, Next decision, the slider, the Project, Agents and Report
tabs), Before / after (and Export HTML report, opened from disk with no server), Present (Space,
the arrow keys, Escape), Compare, Case studies, Watch, Results, Evaluation and the Phase 1
archive. The [user guide](../user_guide.md#studio) says what each screen should do.

File each bug as its own issue (labels `team`, `software`, `bug`) with a screenshot, the screen,
the steps to see it, and your browser and operating system.

**Done when:** every screen is checked in both themes, and the issue lists them with the bugs
you filed.

### S2. Review the Methods section

Due **Nov 30**. Read the final report's Methods section on Overleaf, with
[agentic_design.md](../agentic_design.md), [architecture.md](../architecture.md) (Pipeline, What
the Guard checks, Lanes and policies) and the Phase 2 and Guard parts of [tour.md](tour.md). For
every claim, check it against the code or the docs. Mark what a classmate would not follow.
Leave comments on Overleaf; file wrong or out-of-date docs as issues (labels `team`, `software`)
quoting the passage and proposing better wording.

**Done when:** your comments are on Overleaf, and the issue lists what you read and links your
issues or pull requests.

### S4. Present the Methods part

Due **Nov 20**. Your slot is slides 4 and 5 (how CleanSweep keeps edits safe, and the audit), 2:30 to 3:45. Learn the script in
[presentation.md](presentation.md#maninderjit-safety-and-the-audit-slides-4-and-5) and time it at about 75
seconds. Take the Q&A questions on how it works (questions 3, 10 and 11).

**Done when:** you have given the part in both rehearsals within 80 seconds.

## Badri (data architect), `@byeluri31`

His collaborator invitation is still pending. Until he accepts, he cannot be assigned: the
issues name him in their text, and Ritik assigns them when he accepts.

### D1. Rerun the offline data table builders

Due **Nov 15**, or 2 days after you accept the invitation. Goal: a second machine rebuilds the
data tables (the AIDev funnel, the taxonomy, the rules and the injection plant validator), and
every difference from the committed files is either explained or filed.

**Get the data** (network needed once; nothing here calls an LLM):

```bash
python scripts/data/data_fetch_patchdiff.py      # PatchDiff, about 0.7 GB
hf download hao-li/AIDev repository.parquet pull_request.parquet --repo-type dataset \
    --revision b8dc67df93e7c11f6f20c84129db7232eb1ec253 --local-dir data/raw/aidev
```

SWE-bench Verified (2 MB) downloads itself the first time a script needs it. Ask Ritik for the
mined data the builders read: the contents of `aidev/data_processed/` in the archive tarball,
copied into `data/processed/` (`aidev_requests.parquet`, `aidev_labels.parquet`,
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

**Run the plant validator** on the toy repository (offline; no Docker). It plants the slop and
traps for seeds 1 to 3, checks each seed's plants against the committed benchmark table, then
validates them:

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

Each seed should print "9 plants, same as injection.csv: True", and each line `validate` prints
must have `"invalid": {}`. Do not run `exp_inject.py run`: it would rewrite the committed
benchmark tables from your local runs only.

**Compare with the committed tables:** `git status --short results/`, then
`git diff --stat results/` and `git diff results/data_summary/`. On Ritik's machine these were
the differences; file each one you see as its own issue (labels `team`, `data`):

- `tiers.csv` gains a row, `tier2_v2subset,20,9,6,18`: the Phase 2 subset split was added after
  the committed table was built.
- `aidev_rules.csv` and `detection_by_category.csv`: the same content, in another order for equal
  values.
- `data_aidev_mine.py report` stops with `FileNotFoundError` for `.notes/mining_check.md` unless
  `.notes/` exists (hence the `mkdir`).
- Everything else is identical.

**Clean up:** `git restore results/`, and delete `.notes/mining_check.md` (it holds mined review
comments; never commit it).

**Done when:** every builder has run on your machine, each difference is explained on the issue
or filed as its own issue, and contributions.md has your row.

### D2. Review the Data section and the SlopBench data card

Due **Nov 30**. Read the final report's Data section on Overleaf and
[slopbench.md](../slopbench.md). For every number, find its source (`results/data_summary/`,
`results/summary/v3/slopbench_repos.csv`, `sets.csv`) and check that it matches. Check that a
classmate would follow the text: plain words, Phase 1, 2 and 3, no unexplained terms. Leave
comments on Overleaf; file problems in the data card as an issue, or fix them in a `data/` pull
request.

**Done when:** your comments are on Overleaf, the data card has no open problem, and the issue
says what you checked.

### D3. Present the Data part

Due **Nov 20**. Your slot is slide 3, 1:15 to 2:30. Learn the script in
[presentation.md](presentation.md#badri-data-slide-3), say it aloud with a timer (about 75
seconds), and change the wording until it sounds like you. Check slide 3 with Ritik. Take the
Q&A questions on data (questions 12 and 13).

**Done when:** you have given the part in both rehearsals within 80 seconds.

## Simran (experiment architect), `@SIMRANSHARMA2140`

### E1. Reproduce the tables and check `hypotheses.csv`

Due **Nov 15**. Goal: a second machine confirms that the committed tables rebuild, and that
`hypotheses.csv`, [results.md](../results.md) and the report say the same thing.

1. On a fresh clone of `main`:

   ```bash
   bash scripts/reproduce_tables.sh
   git status --short results/        # must print nothing
   ```

2. Open `results/summary/v3/hypotheses.csv`. For each of H1 to H4, find its row in the README's
   "v3 results" table and in [results.md](../results.md#hypotheses-as-pre-registered-tested-at-the-freeze),
   and check that the verdict and every number match, with the tier named in each safety claim.
   Then do the same for the final report on Overleaf.
3. Optional, if you want to go further: redo one test from the counts in `audit.csv`, `real.csv`
   and `injection.csv` (`scipy.stats` has Fisher's exact test and the Wilcoxon test), using the
   rules in [preregistration_v3.md](../preregistration_v3.md).
4. File each mismatch as its own issue (labels `team`, `experiments`).

**Done when:** the issue has your four verdicts with the numbers you checked, and every mismatch
is filed or explained.

### E2. Review the Results section

Due **Nov 30**. Read the final report's Results section on Overleaf. For every number, find its
source table in `results/summary/` and check that it matches; check that every audit number says
its tier (confirmed, or reading, LLM-judged), that small samples say "suggests" rather than
"shows", that H2 is described as uninformative (the two arms replayed the same run), and that
each figure says which direction is better. Leave comments on Overleaf.

**Done when:** your comments are on Overleaf and the issue says what you checked.

### E3. Present the Results part

Due **Nov 20**. Your slot is slides 6, 7 and 8, 3:45 to 5:00. Learn the script in
[presentation.md](presentation.md#simran-results-slides-6-7-and-8) and check its numbers against
`hypotheses.csv`. Take the Q&A questions on results (questions 4, 5, 14, 15, 16, 17 and 18).

**Done when:** you have given the part in both rehearsals within 80 seconds.

## Ritik (project manager and UI lead), `@ritwiz06`

### P1. Integration and the v3.0 release

Due **Nov 15**. Merge the team's pull requests; answer the issues the team files; check
R1–R30; run the fresh-clone rehearsal; tag v3.0; build, verify and upload the archive tarball to
the ASU Drive. Then update the release date in [handoff.md](handoff.md) and
[status.md](status.md).

### P3. Introduction, demo and slides

Due **Nov 20**. The slide deck (slides 1 to 8 and the backup slides), shared with everyone before
the first rehearsal; the introduction and the demo in [presentation.md](presentation.md#demo-plan),
tested offline with Studio Replay at the first rehearsal.

### P2. Assemble and submit the final report

Due **Dec 4** (confirm on Canvas). Take in the section reviews (S2, D2, E2) and the proofreading
(A1), run the number audit, write the AI-use statement, write the Team Contributions paragraph
from [contributions.md](contributions.md) only, and confirm it with the team. Submit.

## Everyone

### A1. Everyone: proofread the final report

Due **Nov 30**. Read the whole report once on Overleaf. Mark anything you could not explain aloud,
any typo, and any number without a source. Comments on Overleaf; say on the issue when you are
done.

### A2. Everyone: prepare the Q&A

Due **Nov 20**. Read the [Q&A sheet](presentation.md#qa-sheet). Each of us takes the questions
on our part (named in D3, S4 and E3; Ritik takes 1, 2, 6, 7, 8, 9, 19 and 20) and practices a
one-sentence answer for each. Add questions you expect to the sheet by pull request.

### A3. Everyone: two timed rehearsals

Between **Nov 16 and Nov 20**. Two full run-throughs with the slides, the demo and a timer, at
least a day apart. Note each speaker's time; the whole talk must fit in 5 minutes. After each,
fix what ran long and update [presentation.md](presentation.md).

### A4. Everyone: individual peer evaluation

**After the presentation.** Each of us fills in the course's individual peer evaluation on our
own, from what [contributions.md](contributions.md) and the issues show.
