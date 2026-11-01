# Guard on one-shot cleanups

verify(agent patch, agent patch + one_shot_llm diff), tests then probes.

| target set | runs with edits | hidden changed: blocked | by compile | by tests | only by probes | hidden unchanged: blocked (false alarms) |
|---|---|---|---|---|---|---|
| swebench_t1 | 8 | 3/3 | 3 | 0 | 0 | 0/5 |
| swebench_t2 | 49 | 9/9 | 7 | 2 | 0 | 3/40 |
