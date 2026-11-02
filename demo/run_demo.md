# CleanSweep live demo (under 4 minutes)

The demo app is `demo/shop_app`, a small bookstore inventory (`bookshelf` package) with
11 passing tests and 7 planted problems:

| Planted problem | Where | What should happen |
|---|---|---|
| Leftover script | `scratch_restock.py` | deleted (quarantined) |
| Old copy of a module | `bookshelf/inventory_old.py` | deleted (quarantined) |
| Dead function | `bookshelf/utils.py::isbn_checksum_ok` | deleted |
| Exact duplicate helper | `bookshelf/reports.py::_clean_isbn` | replaced by `utils.normalize_isbn` |
| getattr-dispatched command | `bookshelf/commands.py::cmd_restock` | kept (suggest lane; tests use it) |
| Near-duplicate rounding helper | `bookshelf/orders.py::_round_money` | rolled back by the Guard's probes: it rounds .5 up |
| `eval` on input | `bookshelf/storage.py::load_legacy` | reported only |

The feature step (`demo/feature.patch`) adds a `lowstock` command and leaves one new
leftover helper behind (`inventory._print_low_stock`).

## Before the talk (5 minutes, not timed)

1. `.env` has the Voyager key; `VOYAGER_MODEL=qwen36-35b-a3b`.
2. Terminal 1: `source .venv/bin/activate && cleansweep studio` (it opens Studio in the
   browser), then open **Launch**.
3. Terminal 2: `bash demo/prepare_demo.sh`. It builds the app in `.cleansweep/demo/shop_app`
   (gitignored) and prints that path.
4. Check that **Live sweep and replay** lists `20261030_demo_feature_advisory_v1` (the main
   fallback: advisory with the v1.0 defaults) and `20261025_demo_feature_advisory` (the same run before the probes
   existed). Both ship in `demo/replay/`, so Replay works offline, even on a fresh clone.
   Run the live sweep once the day before, so the LLM cache is warm: a cold advisory run took
   6.3 minutes (7 LLM requests); a warm one takes seconds.
5. OpenCode is connected to Voyager and opened in the prepared app folder.

## Script

**0:00–0:25 · The app.** In terminal 2: `cd .cleansweep/demo/shop_app && python -m pytest -q`
(11 passed). Open `scratch_restock.py` and `orders.py` for a second: "an agent built this, and it left things behind."

**0:25–1:15 · An agent adds a feature.** Ask OpenCode:
> Add a `lowstock [threshold]` command that lists the titles with that many copies or
> fewer (default 2), with a test.

Run the tests again (12 passed).
*Fallback if the agent is slow or goes off track:* `bash demo/prepare_demo.sh --with-feature`
(same change, already committed).

**1:15–2:40 · Live sweep, advisory mode.** On **Launch**: **Sweep (v1 pipeline)**, target
**Prepared demo app + feature**, method `cleansweep`, judge mode **advisory**, press **Start**;
the live run opens. Narrate while it runs:
- Open → Analyze → Plan: the detectors, then the LLM judge (the stage bar shows a timer).
- Reviewer plan: rows in the safe lane are edits, rows in the suggest lane are only reported
  (the `cmd_*` commands and the `eval`). The over-engineering review drops "can't happen"
  notes on lines the tests run; the **Run log** at the bottom says which ones and why.
- Guard: each card is one check: apply the batch, compile, import, run the tests, then
  the differential probes ("probes: N cases agree").

*If the judge is still working at 2:10, or the network is slow:* open **Live sweep and
replay**, press **Replay** on `20261030_demo_feature_advisory_v1`, set the speed to 20 and press
**Play** (about 20 seconds).

**2:40–3:30 · What it found.**
- Kept edits (slop meter): the leftover script, the old module, the dead function, the
  exact duplicate, and the helper the agent just left behind. All tests still pass.
- `cmd_restock` stayed in suggest: it is reached through `getattr`, and deleting it
  would break `test_restock`.
- **The Guard catches it.** The near-duplicate `_round_money` passes every test, so the tests
  alone would keep it. Point at its card: "The probes caught a behavior change": the probes
  called `_round_money` and `utils.round_money` on the same inputs, and 0.125 gives 0.13
  before but 0.12 after. The Guard rolled the edit back, and the hidden check says
  **behavior unchanged**. For contrast (only if there is time), replay
  `20261025_demo_feature_advisory` at 50×: before the probes, the same edit was kept and the
  hidden check failed.

**3:30–3:50 · Close** on the results slide: outcome 7/7, hidden behavior unchanged.

## After the talk

Recording a fresh run without the browser:
`python -m cleansweep.live --target .cleansweep/demo/shop_app --judge-mode advisory`. It goes to
`results/raw/live/` (not in git). The shipped copies in `demo/replay/` store paths relative to
the repository, and Replay scores them against `demo/shop_app_expected.json`.
