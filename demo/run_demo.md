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
| Near-duplicate rounding helper | `bookshelf/orders.py::_round_money` | must not change: it rounds .5 up |
| `eval` on input | `bookshelf/storage.py::load_legacy` | reported only |

The feature step (`demo/feature.patch`) adds a `lowstock` command and leaves one new
leftover helper behind (`inventory._print_low_stock`).

## Before the talk (5 minutes, not timed)

1. `.env` has the Voyager key; `VOYAGER_MODEL=qwen36-35b-a3b`.
2. Terminal 1: `source .venv/bin/activate && streamlit run app/dashboard.py`, then open
   **Live sweep** in the browser.
3. Terminal 2: `bash demo/prepare_demo.sh` (prints the app path; keep that terminal there).
4. Check that Replay lists `20261024_demo_feature_gatekeeper` and `20261024_demo_feature_advisory`.
5. OpenCode is connected to Voyager and opened in the prepared app folder.

## Script

**0:00–0:30 · The app.** In terminal 2: `cd "$TMPDIR/cleansweep-demo/shop_app" && python -m pytest -q`
(11 passed). Open `scratch_restock.py` and `orders.py` for a second: "an agent built this, and it left things behind."

**0:30–1:30 · An agent adds a feature.** Ask OpenCode:
> Add a `lowstock [threshold]` command that lists the titles with that many copies or
> fewer (default 2), with a test.

Run the tests again (12 passed).
*Fallback if the agent is slow or goes off track:* `bash demo/prepare_demo.sh --with-feature`
(same change, already committed).

**1:30–3:00 · Live sweep, advisory mode.** On the Live sweep page: target **Prepared demo**,
method `cleansweep`, judge mode **advisory**, press **Run**. Narrate while it runs:
- Open → Analyze → Plan: the detectors, then the LLM judge (the stage bar shows a timer).
- Plan table: green rows are safe edits, orange rows are only reported (the `cmd_*`
  commands, `eval`, the over-engineering notes).
- Guard feed: each card is one check: apply the batch, compile, import, run the tests.

*If the judge is still working at 2:30, or the network is slow:* switch to **Replay**, pick
`20261024_demo_feature_advisory`, speed 20×, press **Replay**.

**3:00–3:45 · What it found.**
- Kept edits (slop meter): the leftover script, the old module, the dead function, the
  exact duplicate, and the helper the agent just left behind. All tests still pass.
- `cmd_restock` stayed in suggest: it is reached through `getattr`, and deleting it
  would break `test_restock`.
- The near-duplicate `_round_money`: in advisory mode the Guard kept it, because every
  test passes, but the hidden check says **behavior changed** (0.125 rounds to 0.12
  instead of 0.13). This is the gap the differential probes close. In gatekeeper mode the
  judge holds it back (replay `20261024_demo_feature_gatekeeper` to show that).

**3:45–4:00 · Close** on the results slide (outcome accuracy and the toy/demo tables).

## After the talk

Delete the prepared copy if you like: `rm -rf "$TMPDIR/cleansweep-demo"`.
Recording a fresh run without the browser: `python -m app.live_runner --target "$TMPDIR/cleansweep-demo/shop_app" --judge-mode advisory`.
