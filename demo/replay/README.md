# Studio recordings

Each folder is a run that `cleansweep studio` can replay offline (Runs, then Replay). They are
demos, not experiment data: the results in `results/summary/` never read them.

| recording | what it shows |
|---|---|
| `20261025_demo_feature_advisory` | v1's sweep (advisory judge) on the demo app with the feature patch, before the probes existed |
| `20261026_demo_feature_advisory_probes` | the same with the differential probes |
| `20261030_demo_feature_advisory_v1` | the same with the v1.0 defaults (7/7, hidden behavior unchanged) |
| `20261101_toy_clean_offline` | the agent team on the toy repository, offline |
| `20261101_manager_conflict_step_back` | the Manager stepping back after a conflict (a decision scenario) |
| `20261101_skill_seekers_case_study` | the Skill_Seekers case study (safe mode); see the note below |
| `20261102_demo_feature_agentic` | the agent team on the demo app with the feature patch |

`scripts/tools/make_recording.py` makes a recording from a run folder: it copies the event log,
the report, the Markdown reports, the final diff and the reply cache, makes paths relative, and
refuses a file with a home path or a secret-looking string. A recording whose text was changed
says so in its `recording.json`.

**Note on `20261101_skill_seekers_case_study`:** two product names in third-party content
replaced by placeholders; nothing else changed. The project names two products in its own code
and docs, and this repository's commit rules do not allow those names; every other byte of the
recording is as the run wrote it.
