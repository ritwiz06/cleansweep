# Handoff

Two pages: where the project is, where things are, who owns what, and what to do if something
breaks. The details are in the other pages of this folder, listed in [README.md](README.md).

## The state

CleanSweep removes leftover AI-written code from a Python project with a team of ten LLM agents,
and keeps an edit only if the project still behaves the same. Phase 1 (the pipeline) and Phase 2
(the team and Studio) are released. **Phase 3, the pre-registered evaluation, is frozen** (Nov 13,
12:00). **The final release is out** (Nov 14): the git tag `v3.0` and its GitHub release.
**Final commit: v3.0.2** (the git tag `v3.0.2`: the course-facing wording and the shorter talk, no
result changes).

| | Result |
|---|---|
| H1 | **Not supported.** On 15 real projects the team's kept edits were wrong far less often than Aider's (4 of 191 against 4 of 13 confirmed by a test or a rule; 13 against 5 counting LLM-judged readings). But held-out tests changed on 4 of the 10 projects both finished for the team, against 0 for Aider, which kept almost nothing (22 lines in 14 runs). |
| H2 | **Not supported, and uninformative.** On 9 of 10 benchmark repositories the team and the team without the resolver produced byte-identical diffs, and the shared reply cache made the arms replay the same run. "3 against 3" is one run counted twice. The tenth timed out in both. |
| H3 | **Supported, by a tie.** Batching used 41% of the requests with 16 against 16 wrong edits over the 20 projects where both finished. Batching's other 36 real-project wrong edits are on openbench, where the team's run hit the request budget and is not paired. Batching stays off by default. |
| H4 | **Supported at the threshold.** 27 of 30 repositories ran end to end. |

**Limits to say out loud:**
- No human checked the labels. Three LLM judges agree with the recorded labels at κ = 0.455
  (wrong vs not wrong) and are right on 11 of 18 verdicts confirmed by a test or a rule.
- The team timed out on 4 of 15 real projects.
- Token counts include only requests that missed the shared cache.
- Nine dated deviations are listed in [preregistration_v3.md](../preregistration_v3.md#deviations).

More: [status.md](status.md).

## Where everything lives

| What | Where |
|---|---|
| Code, tests, docs, committed tables and figures | the GitHub repository `ritwiz06/cleansweep` (private); every change is a pull request ([contributing.md](contributing.md)) |
| The LaTeX sources of the final report and of the paper draft | two Overleaf projects ([shared locations](#shared-locations)) |
| The handoff bundle: the submission files, both Overleaf zips, the decision log and the run log as PDFs, the archive tarball (raw runs, LLM caches) | the ASU Drive folder ([shared locations](#shared-locations)) |
| The working notes | Ritik's local workspace; not shared. [status.md](status.md) is the public summary |
| Your `.env` with your own Voyager key | your machine only; never committed ([setup.md](setup.md#your-voyager-key)) |

## Shared locations

| What | Link |
|---|---|
| The ASU Drive folder with the handoff bundle (its `README.txt` says what each folder holds) | [the Drive folder](https://drive.google.com/drive/folders/1huWKhITpigPLMp9Ax4u992OseHOHv_ov?usp=sharing) |
| Overleaf: the final report | [the report's project](https://www.overleaf.com/project/6af8d81eb843f23a845c8c97/share#9d17cdcd6ece1e3f162abaacd220010ff41344107686ef5a) |
| Overleaf: the paper draft | [the paper's project](https://www.overleaf.com/project/6af8d89f6729c38d6b15b722/share#fbafccb73abc80b3c5f0df4e92ee5d31304ac1b5c8b1b174) |
| The repository | https://github.com/ritwiz06/cleansweep (may move to the team organization) |

After you download the archive tarball, check it against its `.sha256` file: `shasum -a 256 -c`
on macOS and Linux, `certutil -hashfile <file> SHA256` on Windows.

## Repository control

The repository is under Ritik's account, so only Ritik can change its settings, add people or
transfer it. There are two ways to share control:

- **A team organization (recommended):** all four of us as owners, and the repository
  transferred to it. Any of us can then add people or change a setting, and the old address
  redirects to the new one.
- **Collaborators:** the repository stays where it is, and the other three get write access.
  You can push branches and merge pull requests, but only Ritik can change settings or add
  people.

## Who owns what

| Part | Owner | Backup |
|---|---|---|
| Talk: slides 1–3, introduction, progress and demo | Ritik | Maninderjit |
| Talk: slides 4–5, safety and the audit | Maninderjit | Simran |
| Talk: slide 6, data and the benchmark | Badri | Ritik |
| Talk: slides 7–8, results | Simran | Ritik |
| Report: Introduction and Discussion | Ritik | Simran |
| Report: Data (review) | Badri | Maninderjit |
| Report: Methods (review) | Maninderjit | Badri |
| Report: Results (review) | Simran | Badri |
| Final report assembly and submission | Ritik | Simran |
| Bug triage (issues labelled `team`) | Ritik | Maninderjit |
| Peer evaluation | each of us, individually | none |

Ritik drafted every section; the owners review theirs ([tasks.md](tasks.md)). A backup
knows the part well enough to give it if the owner cannot.

## The dates

| When | What |
|---|---|
| Nov 14 | the final release |
| Nov 15 | setup and checks done on your machine |
| Nov 16 – Nov 20 | two timed rehearsals |
| Nov 21 or Nov 28 | the presentation |
| Nov 30 | section reviews and proofreading done |
| Dec 4 (confirm on Canvas) | final report submission |
| after the presentation | individual peer evaluation |

## How to get help

Open an issue on the repository with the label `team`, plus your role label (`data`, `software`,
`experiments`). Say what you ran, what you expected, what happened, and your operating system.
Ritik triages them, and you get an answer on the issue. For a question about a task, comment on
its issue ([tasks.md](tasks.md)).

## Known issues

- **`--sandbox auto` needs Docker for a repository you don't own.** The toy repository counts as
  not yours, so use `--sandbox none` for it. Code you did not write should run in Docker.
- **`data_aidev_mine.py report` needs a `.notes/` folder** to exist (`mkdir -p .notes`), and
  writes mined review comments there; never commit them.
- **Badri's collaborator invitation is still pending.** Until it is accepted, Badri cannot clone the
  private repository or be assigned issues.

## If something breaks before the talk

Studio Replay works offline, with no key, no Docker and no network. From the repository root:

```bash
source .venv/bin/activate
cleansweep studio                     # opens http://127.0.0.1:8765
cleansweep studio --port 8800         # if 8765 is taken
cleansweep studio --no-browser        # then open the printed address yourself
```

On **Home**, press **Try the demo**; or open **Runs** and pick `20261102_demo_feature_agentic`.
Press **Next decision** until the Guard rolls back `_round_money`, then **Before / after**. The talk
itself plays the clip on slide 3; this replay is its backup (slide 11). If Studio will not start,
use the screenshots on slide 11 (`docs/images/studio/present.png` and
`docs/images/studio/before_after_diff.png`). If the install is
broken, see [setup.md](setup.md#troubleshooting). Details of the demo: [presentation.md](presentation.md#demo-plan).
