# CleanSweep v2: agentic design

CleanSweep v1 sweeps a project in one fixed pipeline: detect, judge, batch, guard. v2 adds a
second method, `method=agentic`, and a `cleansweep clean <path>` command. It cleans a whole
Python project the way a careful engineer would: learn the project, measure how healthy it is,
look for slop, investigate each finding, plan the work, apply it one work package at a time with
checks after each, verify everything at the end, and hand over a branch with a report.

v1 stays as it is. `method=cleansweep` and every v1 result are unchanged; the agents reuse v1's
code through a tool registry instead of copying it.

This document is the design. Where the built code differs, `docs/architecture.md` says so.

## 1. Where the design comes from

The team structure follows AutoData (Ma et al., "AutoData: A Multi-Agent System for Open Web
Data Collection", NeurIPS 2025, arXiv:2505.15859). AutoData collects web data with a manager
agent (MGR) and two squads of ReAct-style agents (Yao et al., ICLR 2023): a research squad (plan,
web, tool and blueprint agents) that writes a development blueprint, and a development squad
(engineering, test and validation agents) that builds and checks the program. The agents talk
through OHCache, an "oriented hypergraph cache" with three parts: an oriented message hypergraph
(each message is a hyperedge from one sender to a set of receivers, so a message reaches only the
agents that need it), an oriented hyperedge formatter (each agent's messages follow a structure
made for its role), and a local cache system (large artifacts are stored once and referenced by a
cache ID). AutoData's ablations remove the research squad, the development squad, the whole of
OHCache (broadcast messages), the formatter and the local cache, one at a time. In their results
every ablation scores lower; removing all of OHCache lowers quality the most and raises the
cost, and removing only the local cache costs much more for a small quality change (their
Section 5.4 and Figure 3).

| AutoData | CleanSweep v2 | Why |
|---|---|---|
| Manager agent (MGR) orchestrates and tracks progress; message delivery does not trigger execution | **Manager**: owns the phase machine, assigns work, enforces budgets, decides when the run is done | Same role. Rules propose every step (section 4): the phase order is known in advance, and rules keep the decisions fast, testable and explainable. At each phase boundary the LLM may choose another allowed option (go back, replan, stop); hard rules win. Each decision is logged with its rule or reason. `manager: rules` is the rule-based Manager (an ablation). |
| Research squad: plan, web, tool, blueprint agents | **Explorer** (reads the project, like the web agent reads sources), **Auditor** (runs the detectors and the knowledge base, like the tool agent runs utilities), **Investigator** (a ReAct loop per finding), **Planner** (plan + blueprint agents in one: work packages and `blueprint.md`) | Code cleanup needs one more research step than data collection: each finding has to be investigated before anything is planned. AutoData's plan agent splits the goal up front; our phases already fix the steps, so the Planner's job is the blueprint. |
| Development squad: engineering, test, validation agents | **Engineer**, **Tester**, **Validator**, plus **Fixer** and **Reporter** | AutoData's test agent both runs and debugs; we split debugging out into the Fixer, because a failed cleanup edit must be either repaired in at most 2 turns or rolled back, and every rollback teaches a lesson. The Reporter writes the deliverables. |
| Oriented message hypergraph | **Message board**: messages are directed hyperedges (one sender, a set of recipients); an agent reads only its own inbox | Same idea. |
| Oriented hyperedge formatter | **Message schemas**: one fixed schema per message type, checked when a message is posted | AutoData formats free text into each role's structure; we make the structure a schema, so a malformed message is caught in code. |
| Local cache system: stores a file, broadcasts its cache ID to all agents | **Artifact cache**: artifacts stored once, content-addressed, referenced by ID; the ID travels only in the messages that need it | We do not broadcast cache IDs: the agents that need an artifact are the recipients of the message that names it. |
| — | **Lessons**: every rollback writes a lesson; later decisions must check them and cite the ones that apply | Not in AutoData. A cleanup run repeats the same kind of decision many times, so one mistake should change the next decision. |
| — | **Slop knowledge base**: v1's mined review-comment taxonomy, association rules and the framework conventions table, as a tool | v1's data mining becomes something the agents use, not only a result table. |
| Ablations: no research squad, no development squad, no OHCache (broadcast), no formatter, no local cache | No research squad, broadcast messages, artifacts inlined, no lessons, no coverage guidance, a single ReAct agent with every tool | The same style of ablation. "No development squad" cannot run in cleanup (nothing would be applied or checked); the one-shot LLM baseline plays that role. The formatter cannot be removed either: the JSON protocol needs the schemas. A single agent is added because it is the obvious simpler alternative to a team. |

MetaGPT (Hong et al., ICLR 2024) also gives agents roles and a shared message pool in which
agents subscribe to what their role needs. Our board is closer to AutoData's: the sender names
the recipients, so routing is decided when a message is written, not by each reader.

## 2. Tool-calling protocol (measured in Phase 0)

Every agent step is one LLM reply that picks one tool, or finishes. We measured two ways to do
that on Voyager, with 10 different Investigator steps (each with a known set of sensible next
tools), for the default model and two coding models, with reasoning on and off: 120 requests,
2026-10-31, 3 in parallel. Raw replies: `results/raw/tool_calling/` (not in git); the full table
is in the project's run log.

| Model | Protocol | Reasoning | Valid calls | Sensible tool | Median s | Median completion tokens | Median prompt tokens |
|---|---|---|---|---|---|---|---|
| qwen36-35b-a3b (`VOYAGER_MODEL`) | native tool calls | off | 9/10 | 8/10 | 1.2 | 54 | 1,046 |
| qwen36-35b-a3b | native tool calls | on | 8/10 | 7/10 | 3.8 | 187 | 1,046 |
| qwen36-35b-a3b | JSON ReAct | off | **10/10** | 9/10 | 1.4 | 49 | 510 |
| qwen36-35b-a3b | JSON ReAct | on | 10/10 | 8/10 | 4.9 | 189 | 510 |
| qwen3-coder-next | native tool calls | off / on | 10/10, 10/10 | 8/10, 8/10 | 4.2 | 45 | 1,163 |
| qwen3-coder-next | JSON ReAct | off / on | 10/10, 10/10 | 9/10, 9/10 | 3.9 | 42 | 495 |
| kimi-k2-7-code | native tool calls | off / on | 10/10, 10/10 | 9/10, 9/10 | 7.3–8.2 | 132 | 522 |
| kimi-k2-7-code | JSON ReAct | off / on | 10/10, 10/10 | 8/10, 8/10 | 16–18 | 238–255 | 492 |

What we learned:
- Native tool calls mostly work, but the default model sometimes answered with 2 or 3 parallel
  calls when the protocol asks for one (3 of its 20 native tries).
- The JSON ReAct protocol was valid on the first try in all 60 requests; the repair retry was
  never needed.
- With native tools, the server writes the tool definitions into the prompt in a long form: the
  qwen models' prompts were twice as large (about 1,050–1,160 tokens against about 500).
- Reasoning off is as reliable as reasoning on for choosing a tool, and 3–4 times cheaper in
  completion tokens on the default model. The switch has no visible effect on qwen3-coder-next
  (it does not reason) or kimi-k2-7-code (it always reasons).
- Most "not sensible" choices were a `read_code` step before deciding, which is cautious rather
  than wrong; the expected sets were strict.

**Choice: the JSON ReAct protocol for every agent, reasoning off for tool-choosing steps,
`VOYAGER_MODEL` by default.** It was the most reliable, it halves the prompt, and it runs through
the existing LLM client unchanged (its response cache, retries and `FakeLLM` for tests). A step's
reply is either

```json
{"thought": "<one line>", "tool": "<tool name>", "args": {"...": "..."}}
```

or

```json
{"final": {"...": "the agent's output schema"}}
```

The reply is checked against a JSON schema (the tool's argument schema, or the agent's output
schema). An invalid reply gets one repair turn that quotes the problem; a second invalid reply
ends the step as a failure, which the agent handles cautiously (an Investigator's candidate goes
to `suggest`).

## 3. Orchestration: LangGraph

The team runs as a LangGraph `StateGraph` with one node per agent (10 nodes). Every worker node
returns to the Manager node, and the Manager's conditional edge picks the next node or ends the
run. The JSON protocol does not rule LangGraph out: tool calls happen inside a node, so the
graph only sees which agent works next.

Why LangGraph and not v1's plain loop: the Manager-as-router shape is exactly a `StateGraph` with
conditional edges, step-backs are just edges, and the graph can be drawn for the docs and the
Studio. What we do not use: LangGraph's checkpointer (the event log is our record, and Replay
folds it) and its LLM wrappers (agents call our own client). Parallel Investigators run in a
thread pool inside the Investigator node (at most 3 requests at once), which keeps the event
order and budgets in one place. The graph state holds only plain data (phase, queues, counters,
artifact IDs); the workspace, LLM client, board and cache live in a runtime object the nodes
share.

## 4. The phases (the Manager's state machine)

| # | Phase | Agents | Produces | Next | May step back to |
|---|---|---|---|---|---|
| 1 | ONBOARD | Explorer | project brief (artifact), secret scan | BASELINE | — |
| 2 | BASELINE | Tester | the project's environment (a venv in the run folder with the project installed; the copy's `src/` first on `PYTHONPATH`), then 3 test runs: passing, failing and flaky tests (artifacts) | AUDIT | ONBOARD, once: the install or test command failed, the Explorer revises the brief |
| 3 | AUDIT | Auditor (one instance per category group) | candidates with detector evidence and knowledge-base priors | INVESTIGATE, or REPORT if there are none | — |
| 4 | INVESTIGATE | Investigator (up to 3 in parallel) | a verdict per candidate: safe / suggest / drop, an evidence chain, cited lessons | PLAN | — |
| 5 | PLAN | Planner | work packages and `blueprint.md`; with `--approve-plan`, the run pauses for approval | EXECUTE, or REPORT if nothing is safe | — |
| 6 | EXECUTE + VERIFY | Engineer → Tester → Validator → Fixer, one package at a time | per package: commit kept, repaired or rolled back; lessons | next package, then FINAL VERIFY | PLAN, at most twice: a rollback invalidates later packages that depend on it |
| 7 | FINAL VERIFY | Tester, Validator | full suite against the baseline; probes on every changed public function; UI and dependency checks where they apply | REPORT | EXECUTE, once: the final suite is worse than the baseline; packages are reverted by bisection until it is not |
| 8 | REPORT and DELIVER | Reporter | `CLEANUP_REPORT.md`, PR description, changelog entry, the branch | done | — |

The rule over everything: **never make the project worse.** The final suite is at least as good
as the baseline: every test that passed in all 3 baseline runs still passes (flaky tests are
reported, not compared), and no new errors appear. A test that only existed in a file the
cleanup deleted as a leftover is listed in the report, never silently dropped. If the baseline
cannot run at all, `safe` mode stops after PLAN and delivers the plan as suggestions only.

Every step back is a `phase_change` event with its reason. Each back edge has a limit, so a run
always ends.

**The LLM-guided Manager** (`core.agents.manager: llm`, the default when an LLM is set; `rules`
keeps the rule-based Manager, and is one of the ablations). The rules propose every step. At each
phase boundary, after a rolled-back package, the first time a run cap (LLM calls, minutes or
test runs) is 85% used with packages left, and when FINAL VERIFY finds the suite worse than the
baseline, the Manager also sends the LLM one short JSON request (reasoning off): the run's status
(phase, candidates and verdicts, undecided candidates, packages and packages left, baseline,
budget used, step-backs left), what the rules propose, and the options the hard rules allow, and
it picks one, with a reason:
- `continue`: the rules' step;
- `go_back:INVESTIGATE`: investigate again the candidates the Investigator could not decide
  (its budget ran out or its answer stayed invalid), with twice the steps; offered after
  INVESTIGATE and PLAN when there are such candidates;
- `replan`: back to PLAN for the packages not started (after a rolled-back package);
- `stop`: skip the work not started, verify what was applied, and report;
- `revert_all` (FINAL VERIFY only): undo every kept package instead of undoing packages from the
  last one until the suite is back to the baseline.

Hard rules still win: budgets (the Manager's own LLM budget, `manager_budget`, and the run's),
never worse than the baseline (after a worse FINAL VERIFY both options undo packages and neither
may stop; a stop after anything was applied still goes through FINAL VERIFY), and at most 2
step-backs chosen by the LLM per run. A reply that is not valid JSON, or names an option that is not offered, leaves the step
to the rules. Every pick is a `decision` event (rule `llm_manager`) with its reason, the options
and the rules' proposal. Points with only one option ask nothing.

## 5. The ten agents

Budgets are per agent instance: steps (tool calls), LLM calls and seconds. They are defaults in
`configs/base.yaml` under `core.agents.<agent>`; Phase 2 tunes them from measured runs. When a
budget runs out, the agent stops and the Manager takes the cautious path (a candidate goes to
`suggest`, a package is rolled back).

| Agent | Squad | Job | Tools (wrapping existing code) | Reads (message types) | Writes | Default budget (steps / LLM calls / s) |
|---|---|---|---|---|---|---|
| Manager (MGR) | — | phases, assignments, budgets, progress, done | board, budgets, phase machine | every result message addressed to it | `task`, `phase_change` events | run budget (`--budget`) |
| Explorer | research | the project brief: languages, packages, frameworks, entry points, install and test commands, CI and config files | `list_files`, `read_file` (redacted), `read_config` (pyproject, setup.cfg, requirements, tox/nox, CI), `build_graph` (entry points), `frameworks.framework_for`, secret scan | `task` | `brief` | 12 / 4 / 300 |
| Auditor | research | find candidates | v1 detectors (`reviewer.detectors.run_detectors`: leftovers, dead code, unused imports, unused dependencies, security, format, wrappers, duplicates), the new line-level detectors (section 9), the over-engineering review (thorough mode), `query_knowledge_base` | `task`, `brief`, `lesson` | `candidates` | 6 / 2 / 300 per instance |
| Investigator | research | a ReAct loop per candidate: decision, an evidence chain where every step cites a tool result, the lessons it used | `find_references` (code graph callers + text search in code, tests, configs, strings), `read_code`, `check_dynamic_use` (`CodeGraph.dynamic_risk`, `framework_callback`), `find_related_tests`, `check_dependency_usage`, `compare_functions` (AST equality + shingle similarity from `analysis.minhash`), `query_lessons`, `query_knowledge_base`, `read_artifact` | `candidates` (its own), `lesson` | `verdict` | 6 / 6 / 600 per candidate |
| Planner | research | turn safe verdicts into work packages ordered by risk and dependencies; each has a goal, files, edits, a verification plan and a rollback plan; writes `blueprint.md` | `scheduler.batching.risk_tier`, code graph (dependencies between edits), `query_lessons`, `query_knowledge_base` | `verdict`, `baseline`, `lesson` | `blueprint` | 8 / 3 / 300 |
| Engineer | development | apply one package: deterministic edits first (`guard.edits.apply_edit`, `reviewer.rewrite`), an LLM rewrite only when no deterministic edit exists (thorough mode); one commit per package | `apply_edit`, `apply_patch`, `Workspace.checkpoint`, commit | `blueprint` / `task` (one package) | `package_applied` | 8 / 2 / 300 per package |
| Tester | development | install and run the baseline; per package, the related tests (selected from the code graph) and then the full suite; the full suite at the end | `Workspace.run_tests`, `coverage_json`, related-test selection | `task`, `brief`, `package_applied` | `baseline`, `test_result` | per package: test timeouts only |
| Validator | development | coverage-guided differential probes until the changed lines are covered or the budget ends; the UI snapshot check where a UI framework is in the brief; the dependency-uninstall check; the public-API check | `guard.difftest` (targets, probes, harness, compare), coverage of the probes, `Workspace.hide_packages`, `detectors.is_public_api`, UI snapshot harness | `package_applied`, `test_result` | `validation` | 3 probe rounds / 3 / 600 per package |
| Fixer | development | diagnose a failure; repair in at most 2 turns or roll back; write a lesson either way | `reviewer.repair.propose_fix`, `Workspace.apply_patch`, `Workspace.rollback`, the Tester's and Validator's checks | `failure` | `repair`, `lesson` | 2 turns / 2 / 600 per failure |
| Reporter | development | `CLEANUP_REPORT.md`, the PR description, a changelog entry | report templates over the cache (numbers come from artifacts, not from the LLM) | `final_check`, every `verdict` and `repair` | `report` | 4 / 2 / 300 |

Each agent has a plain-language prompt file in `src/cleansweep/agents/prompts/<agent>.txt`.

### The Investigator's output

```json
{"item_id": "dead_code:shop/utils.py::format_legacy_date",
 "decision": "safe | suggest | drop",
 "reason": "one or two sentences for a human",
 "evidence": [{"step": 1, "tool": "find_references", "result": "R1", "says": "0 references in code or tests"}],
 "lessons_cited": ["L2"],
 "confidence": 0.8}
```

Every evidence step must cite a tool result ID from this investigation. A `safe` decision with
no evidence, or a decision that ignores a lesson whose pattern matches the candidate, is
rejected by the schema check and repaired once; if it is still invalid, the candidate goes to
`suggest`.

### Work packages

```json
{"package_id": "P3", "goal": "Remove the unused helpers in shop/utils.py",
 "items": ["..."], "files": ["shop/utils.py"], "edits": [{"item_id": "...", "action": "delete_unit"}],
 "risk": 1, "depends_on": ["P1"],
 "verify": {"tests": ["tests/test_utils.py"], "probes": ["shop.utils.parse_price"], "checks": ["public_api"]},
 "rollback": "git reset to the commit before P3; nothing else changes"}
```

## 6. Message board

Every message is a directed hyperedge: one sender, a set of recipients, a type, a body that
follows the type's schema, a list of artifact IDs, an ID and the ID of the message it answers.
The board keeps every message (that is the run's communication record); `inbox(agent)` returns
only the messages addressed to that agent, and an agent's prompt is built only from its inbox.

| Type | Sender | Recipients | Body (besides artifact IDs) |
|---|---|---|---|
| `task` | Manager | one agent | phase, goal, inputs, budget |
| `brief` | Explorer | Manager, Tester, Auditor, Planner, Validator | languages, frameworks, install and test commands, entry points, UI framework, secret findings (masked) |
| `baseline` | Tester | Manager, Planner, Validator, Fixer | passed / failed / errors / flaky counts, failing and flaky test IDs |
| `candidates` | Auditor | Manager, Investigator | candidate list: item ID, unit, category, detector evidence, knowledge-base prior |
| `verdict` | Investigator | Manager, Planner | decision, reason, evidence chain, lessons cited, confidence |
| `blueprint` | Planner | Manager, Engineer, Tester, Validator, Reporter | package IDs in order |
| `package_applied` | Engineer | Manager, Tester, Validator | package ID, commit, edits applied, edits that could not be applied |
| `test_result` | Tester | Manager, Validator, Fixer | package ID, ok, new failures |
| `validation` | Validator | Manager, Fixer, Reporter | package ID, ok, probe outcome, coverage reached, dependency and public-API results |
| `failure` | Manager | Fixer | package ID, the stage that failed |
| `repair` | Fixer | Manager, Engineer, Reporter | package ID, repaired or rolled back, turns used |
| `lesson` | Fixer | Manager, Auditor, Investigator, Planner | lesson ID, pattern, reason |
| `final_check` | Tester, Validator | Manager, Reporter | suite against the baseline, probe and UI results |
| `report` | Reporter | Manager | the delivered files |

In the **broadcast** ablation, every message goes to every agent, so each agent's inbox (and
prompt) holds everything.

## 7. Artifact cache

Large things are stored once and referenced by ID: the brief, the code graph, test logs,
coverage, diffs, probe tables, the blueprint, source snippets and the reports. An ID looks like
`art:diff:3f2a9c1b` (kind plus the start of the content's sha256), so storing the same content
twice gives the same ID. Artifacts live in `<run dir>/cache/`. A message carries artifact IDs and
a short digest (at most about 300 characters); an agent that needs more calls `read_artifact(id,
start, end)`, which returns a bounded slice. In the **inlined** ablation, artifacts are pasted
into the messages, and so into the prompts.

## 8. Slop knowledge base

v1's data mining becomes a tool the Auditor, Investigator and Planner can query:
- the review-comment taxonomy (`results/data_summary/aidev_taxonomy.csv`: 15 clusters of 535
  maintainers' removal requests on agent pull requests),
- the association rules (`aidev_rules.csv`: agent and change type → slop type, with support,
  confidence and lift),
- detection by category (`detection_by_category.csv`),
- the framework conventions table (`cleansweep.analysis.frameworks.FRAMEWORKS`: methods a
  framework calls by name).

`query_knowledge_base(category=..., agent=..., change_type=..., file_pattern=..., framework=...)`
returns the matching rows, best lift first, with a one-line reading. The Auditor uses it to give
each candidate a prior (for example, the mined rule "agent=Copilot, leftover_file, PR merged →
the file is a test", confidence 0.68, lift 2.0, says leftover files in such pull requests are
mostly test files); the Investigator and Planner use the framework table to keep framework
callbacks out of packages.

## 9. Line-level detectors (Phase 2)

| Detector | Category (new) | Lane | Source |
|---|---|---|---|
| unused local variables (the value is kept as a statement when it is a call; an unused `except ... as e` loses its name) | `unused_variable` | safe | ruff F841 |
| debugger calls (`breakpoint()`, `pdb.set_trace()`) and debug prints (a string starting with "debug", ">>>", "here", or a self-documenting `f"{x=}"` as written in the source; a hand-written `"x={x}"` is output) | `debug_leftover` | safe; a debugger call under an `if` (an opt-in switch such as `if self.debug_on_nan:`) and other prints in library modules: suggest (a debugging feature or intended output); CLI modules are skipped | `ast` |
| commented-out code: the longest runs of comment lines that parse as Python statements (prose next to them stays; so does prose that parses by accident: list items such as `- name(a, b)`, a lone expression with a space before its parentheses such as `Paragraph (default)`, and a call of a capitalized name on bare words such as `Author(s)`) | `commented_code` | safe | `tokenize` + `ast` |
| TODO/FIXME/XXX/HACK comments on their own line | `todo_note` | suggest (a person decides) | `tokenize` |
| `if c: return True else: return False` → `return bool(c)` (and the negation), a boolean test with the same operand twice | `redundant_check` | safe; `x == True` → `x`: suggest (not the same for non-bool values) | `ast` |

Each edit is a zero-context diff with the new action `edit_lines`: the Engineer finds the exact
old lines nearest their recorded position, so edits that moved them, even on the next line, do
not matter, and nothing is written unless every hunk fits. Emptied blocks get `pass`. The
detectors run as a second Auditor instance in the same scope as v1's (the agent's files and
lines on SWE-bench and AIDev). Line-level items keep their detector's lane (the checks decide),
so they cost no LLM requests. Comment-only packages (commented code, TODO notes, formatting) are
proven by AST equality. These are additive contract changes: five categories and one action
appended to the lists in `core.models`; v1's detectors never produce them.

## 10. Lessons

When the Fixer rolls a package back (or repairs it), it writes a lesson:

```json
{"lesson_id": "L2", "pattern": {"category": "dead_code", "unit_kind": "function",
  "name_pattern": "on_*", "framework": "textual", "file_glob": "ui/*.py"},
 "reason": "Textual calls on_* methods by name; deleting one broke a UI test",
 "source": {"package": "P4", "item": "...", "check": "tests"}}
```

Lessons go to the board (to the Manager, Auditor, Investigator and Planner) and to the run's
lesson store. Before deciding, the Investigator calls `query_lessons`; a lesson whose pattern
matches the candidate must be cited in the verdict, or the verdict is rejected. Lessons are kept
per run by default (so repeated experiment runs stay independent); `core.agents.lessons_file`
keeps them across runs.

## 11. Coverage-guided probes

v1's Guard asks the LLM once for probe cases. The Validator keeps going
(`agents/coverage_probes.py`): after each round, the probe harness runs under coverage.py on
the version before the change (where deleted lines still exist), and the next request
(`prompts/validator.txt`) shows the target's code with line numbers, the lines no probe has run
and the cases so far, and asks for cases that reach them. The target lines are the changed
statements inside functions that still exist, and the whole body of a removed duplicate or
wrapper (its probes run against the replacement); deleted dead code is left out (nothing can
call it; the module check covers it). It stops at 90% of the target lines, after 3 rounds, or
when the budget ends, records the coverage reached, and compares before and after on every case,
as v1 does. Coverage is measured in direct mode (local workspaces); runner mode (Docker) keeps
one round. The `no_coverage` ablation runs v1's single round. A test shows the point: a behavior
change in a branch the first round never runs passes v1's check and is caught by the second
round.

Functions in standalone scripts are probed too. A file with no `__init__.py` beside it, or with a
name that cannot be imported (`benchmark/compute-time.py`), gets an importable module name
(`benchmark.compute_time`), and the harness loads it by path before the probes run: its
`__name__` is not `"__main__"`, so its main block does not run; its folder goes on `sys.path` for
sibling imports; and the third-party modules it imports that the project's environment lacks (a
PEP 723 script's own dependencies, say) are replaced by stubs, which the probe note lists. The
project's own modules are never stubbed. v1 never asks for this, so its probes are unchanged.

## 12. Safety

- **Never touch the original.** `clean` copies the project into a scratch workspace (a git clone
  when the original is a git repository, so the branch applies to its history; otherwise a copy
  with a fresh `base` commit). The result is a branch in that workspace, one commit per work
  package, plus `CLEANUP_REPORT.md` and `blueprint.md`, and a patch series in `--out`. Nothing is
  pushed or applied to the original.
- **Secrets never reach the LLM.** ONBOARD runs a secret scan over the copy (private keys,
  cloud and API key patterns, tokens, passwords in configs, `.env` files, key and credential
  files). Secret files are never read into a prompt (the tools return "[withheld]"), and every
  message sent to the LLM passes through one redaction wrapper around the client, so no agent can
  bypass it. Events and artifacts sent to the browser are redacted the same way.
- **Checks on every package**: compile and import, related tests then the full suite against the
  baseline, coverage-guided probes, the public-API check, the dependency-uninstall check where
  the workspace can uninstall, and the UI snapshot check for Textual apps (`guard/ui_check.py`:
  in BASELINE every screen and widget class is mounted headless twice with `App.run_test`, and
  classes that differ between the two runs are left out; after each package a stable class that
  shows another widget tree or text, disappears without the package deleting it, or a module
  that stops importing fails the package; other UI frameworks are recorded as "not
  applicable"). Two rules from the Phase 3b case studies: a rewrite (a merged duplicate or an
  inlined wrapper) is verified only by probe cases on its own target that return something
  other than None (a method that only writes to a database looks the same either way), and a
  removed dependency that carries a version specifier while another dependency requires it is a
  version pin, not an unused dependency (the tests pass because it stays installed, but a fresh
  install would resolve another version). A failed package is repaired (at most 2 turns) or
  rolled back.
- **Cautious defaults**: an exhausted budget, an invalid reply after the repair turn, or an LLM
  failure sends the candidate to `suggest`; a package that cannot be verified is rolled back; an
  edit that raises (a file that does not parse, such as a template named `*.py`) is undone and
  skipped, and the package goes on.
- A single LLM request that takes over 10 minutes is cancelled and logged (the client's timeout
  is 600 s), and the step counts as failed.

## 13. Latency and budgets

Voyager requests take 30–200 s under load (1–5 s when it is quiet, as in the Phase 0
measurements). The design keeps the number of sequential requests small:
- deterministic tools do the work (detectors, graph, edits, tests); the LLM chooses and explains;
- reasoning is off for tool-choosing steps;
- up to 3 LLM requests run at once (Investigators, Auditor instances);
- prompts carry artifact IDs and digests, never whole artifacts;
- `--budget` caps the run (LLM calls, minutes, test runs); per-agent budgets cap each instance.

If an agentic run on the toy repository is more than 3 times slower than v1, the budgets are cut
and the reason recorded.

## 14. Event schema v2

Every event is one JSON line in `events.jsonl`:

```json
{"v": 2, "id": "e0042", "parent": "e0040", "t": 12.53, "ts": "2026-11-01T10:02:13Z",
 "run_id": "...", "agent": "investigator#2", "squad": "research", "phase": "INVESTIGATE",
 "kind": "tool_call", "recipients": [], "artifacts": ["art:graph:91c0d2aa"],
 "payload": {"tool": "find_references", "args": {"name": "export_csv"}}}
```

Kinds: `thought`, `tool_call`, `tool_result`, `message`, `decision`, `check`, `budget`,
`lesson`, `phase_change`, plus `run_start`, `run_end`, `llm_start`, `llm_end` and `log`. It is a
superset of v1's events: `t` and `kind` are kept, and the emitter also calls v1's
`on_event(name, payload)` hooks (`open`, `analyze`, `plan`, `baseline`, `check_start`, `check`,
`report`) at the matching moments, so v1 readers (the Live sweep page, `read_events`, Replay)
still work on an agentic run.

## 15. Command line

```
python -m cleansweep clean <path> [--mode safe|thorough] [--budget llm=150,minutes=60,tests=80]
                                  [--approve-plan] [--dry-run] [--out <dir>] [--model M]
                                  [--no-llm] [--config FILE] [--quiet]
python -m cleansweep clean --resume <out dir or run id> [--quiet]
python -m cleansweep clean <path> [--sandbox auto|docker|none] [--untrusted] ...
```

- `--mode safe` (default): deterministic edits only, every package fully verified, anything
  uncertain goes to `suggest`. `thorough`: a duplicate or wrapper the Investigator judges safe is
  applied even when its detector lane is `suggest` (a near-duplicate, say); when no
  deterministic rewrite exists, the Engineer asks the LLM for one (exact search-and-replace
  edits in the duplicate's own file, which must still parse; uses in other files rule it out);
  the probes get 2 more rounds, must run cases on every rewrite's own target, and the Fixer may
  repair a probe-found behavior change. Everything else is as in safe mode.
- `--approve-plan` pauses after PLAN and shows `blueprint.md`; the run continues only on approval.
- `--dry-run` stops after PLAN and changes nothing.
- `--out` (default `<project>-cleanup-<time>/` next to the project; a folder inside the project
  is refused): the scratch workspace with the branch, `CLEANUP_REPORT.md`, `blueprint.md`,
  `PR_DESCRIPTION.md`, `CHANGELOG_ENTRY.md`, the patch series, `events.jsonl`, the artifact cache
  and `report.json`. The LLM and probe caches go to `~/.cache/cleansweep/`, so nothing is written
  inside the project, whatever folder the command runs from.
- `--exclude FOLDER` (repeatable) leaves folders alone; `--test-args "..."` passes pytest
  arguments (e.g. a marker selection) to every test run; `--no-install` runs the tests with
  CleanSweep's interpreter instead of installing the project into its own venv. The venv lives
  in the output folder, never in the workspace, and falls back on CleanSweep's packages (pytest,
  coverage), so the tests always exercise the cleaned copy, not an installed original.
- Slow suites (`core.agents.full_suite_max_s`, default 120 s): each package runs its related
  tests; the full suite runs once in FINAL VERIFY, and if that is worse than the baseline the
  Manager reverts packages from the last one.
- `--config FILE` (default: the project's `.cleansweep.yaml`, if any) sets `mode`, `budget`,
  `exclude`, `test_args`, `install` and `model` for the project; the options above override it.
- `--no-llm` runs offline: the Investigator gathers the same evidence with its tools and decides
  by rules (keep the detector lane unless a lesson fits or the code may be used dynamically).
- The test command (`agents/runners.py`, recorded in the brief with where it came from): pytest
  when the project has pytest settings (pytest.ini, `[tool.pytest.ini_options]`,
  `[tool:pytest]`, tox.ini `[pytest]`); else the pytest or unittest command that tox
  (`[testenv] commands`, `[tool.tox]`), nox (`session.run`) or the Makefile's `test` target runs,
  with its test paths (tox, nox and make themselves are not run); else pytest when there is a
  `conftest.py`; `python -m unittest discover` from the test files' folder when every test file
  is `unittest.TestCase` only (a runner writes a JUnit report, so each test has its own status);
  `make test` as one pass/fail result when the target runs something else; pytest for the other
  test files; none without test files. `--test-args` asks for pytest.
- The environment (`agents/environment.py install_plan`): `pip install -e .[extras]` for a
  package (`[project]`, `[tool.poetry]`, a build system, setup.py or setup.cfg; test/dev extras
  from pyproject or setup), PEP 735 dependency groups and poetry's test/dev groups (names only),
  and `requirements.txt` plus the dev/test requirement files (every `requirements*.txt` for a
  project with neither). With `poetry.lock` and poetry installed, `poetry install --with <test
  groups>`; with `uv.lock` and uv, `uv sync --frozen`; both install into the run's venv, and pip
  is their fallback. A `src/` folder with a package or module goes first on `PYTHONPATH`.
- No usable tests (`core.agents.no_tests`, `probes` for `clean`, `plan` for experiment runs):
  when the baseline gives no test result (no test files, the test command fails, nothing
  collected), `plan` delivers the plan as suggestions, as v2.0 did; `probes` goes on with static
  evidence and probes only. Before PLAN, file and dependency removals and removals of public API
  stay suggestions; each package then needs the probes to cover every edit (a removal: its
  module imported before the change and the module check passed; any other edit: the probes ran
  at least `coverage_target` of its changed lines; an AST-equal edit is covered by that check),
  else it is rolled back with no lesson. FINAL VERIFY has nothing to run.
- Notebooks (`core.agents.notebooks`, `hold` for `clean`, `ignore` for experiment runs): no test
  runs a notebook, so a function, class, file or dependency that a notebook's code cells name
  stays a suggestion (`auditor.hold_notebook_uses`, before PLAN).
- `--sandbox` (`sandbox/container.py`; Studio passes the same `sandbox` value): `docker` runs
  every command that runs the project's code (the install, the tests, compile and import
  checks, probes, the UI harness) in a `python:3.11` container with the workspace mounted at
  `/repo`, installs the project there with pip from the same install plan (no poetry or uv in
  the container) plus pytest and coverage, then `docker network disconnect`s it before any of
  the project's code runs, as the AIDev workspace does; the detectors, ruff and git stay on the
  host and only read files, and for a sandboxed git repository no git command that reads its
  working tree runs in the original (its `.git/config` could name a filter or fsmonitor
  command). `none` runs on the host as before. `auto` (the CLI's default, also from
  `CLEANSWEEP_SANDBOX`) is none for a folder in a git repository with at least one commit whose
  author email is the user's `git config --global user.email` (the repository's own config
  does not count: it could name its authors), docker otherwise; `--untrusted` forces docker.
  The choice and its reason are printed and written to the report. Docker missing or not
  running ends the run with "stopped: Docker is not ..., nothing applied". The container is
  removed when the run ends (the workspace folder stays); a resumed run starts a new one.
  `docker/Dockerfile` builds an image with CleanSweep installed (`CLEANSWEEP_SANDBOX=none`
  inside: that container is the sandbox); see the README for the one-line `docker run`.
- `--resume` (`agents/checkpoint.py`): at each safe point (a phase entered, a work package
  finished) the run's state goes to `checkpoint.json` in the output folder, and `run.json` holds
  the options it started with. A resumed run resets the workspace to the checkpoint's commit
  (a package cut off half way starts again), restores the state, appends to `events.jsonl` and
  goes on from that phase; the report says where it resumed.
- Every run that gets as far as its output folder ends with `CLEANUP_REPORT.md`, `report.json`
  and one verdict from a fixed set (`agents/reporter.py VERDICTS`): "everything runs" (tests
  ran, the final suite is at least as good as the baseline), "nothing applied" (a dry run, or
  nothing survived its checks), "not verified by tests" (no usable tests; the edits applied are
  probe-covered), "not verified" (edits applied, the final check could not confirm them),
  "stopped: <reason>, nothing applied" (an agent or the setup failed before anything was
  applied, or Ctrl-C; the error's trace goes to `error.log`, never to the terminal).
- Exit code 0 when the result is "everything runs" or "nothing applied", 130 after Ctrl-C (with
  the `--resume` command to continue), 1 otherwise or on an error (one readable line), 2 for a
  bad option.

`run_sweep(target, cfg, method="agentic", seed, on_event)` runs the same team for experiments and
returns a normal `SweepReport`, so v1's collection and statistics scripts read it unchanged.

### Watch mode (R9)

```
python -m cleansweep watch <repo> [--budget-tests N] [--interval S] [--once | --polls K]
                                  [--out <dir>] [--mode safe|thorough] [--no-llm]
```

`agents/watch.py` follows a git repository: each poll looks at the newest commit, measures the
slop there with the static detectors (the same measurement as v1's Scheduler replay: leftover
files, dead code, unused imports, wrappers, safe lane), and decides:
- wait when nothing is open, or when the test budget left can't pay for even one package (three
  baseline runs, one run per package of four items, the final suite);
- clean when the open slop is at least 2% of the Python lines (v1's adaptive threshold), when
  the commits since the last clean added at least 3 items, or after 20 commits with slop open;
  a budget too small for every open item caps the clean at the test runs left;
- otherwise wait, with the share, the items open and new, and the commits since the last clean.

A clean runs `clean` on a `git archive` copy of the commit (the repository is never written to);
its items count as delivered until the next measurement no longer finds them merged. Every poll
appends a line to `<out>/watch_log.jsonl` (commit, subject, slop by category, decision, reason,
the clean's folder and outcome, test runs used); `watch_state.json` lets a watch resume.
`simulate_watch` applies the same rule to a recorded history from the v1 replay's cached
measurements (`scripts/experiments/v2/exp_watch.py simulate` → `results/summary/v2/watch_replay.csv`);
`exp_watch.py demo` watches the demo app and commits `demo/feature.patch` as a new commit.

## 16. Ablation switches

Each ablation is a config switch under `core.agents.ablation`, recorded in the report's stats:

| Switch | What changes |
|---|---|
| `no_research` | v1 detectors go straight to the development squad (one package per safe item, no Explorer, Investigator or Planner LLM steps) |
| `broadcast` | every message goes to every agent |
| `inline_artifacts` | artifacts are pasted into messages and prompts |
| `no_lessons` | the Fixer writes no lessons and nobody queries them |
| `no_coverage` | the Validator runs one probe round, as v1 does |
| `single_agent` | one ReAct agent (`agents/solo.py`, agent `solo`) with every tool and one context, under the same total budget: it lists the detectors' candidates, investigates with the Investigator's tools, applies edits, runs the tests and the coverage-guided probes, and keeps or reverts each edit itself; no Manager, phases, board, packages or lessons. The baseline and the final suite are measured for the report, not enforced |
| `core.agents.manager: rules` | the rule-based Manager: no LLM decisions at phase boundaries (a separate setting, run as an ablation) |
| `core.agents.investigate: adaptive` | adaptive investigation (a separate setting; `all` is the default, `none` decides every candidate by rules): only the uncertain candidates go to an Investigator, namely near-duplicates and wrappers, dependency removals, framework-convention methods, units the graph says may be used dynamically, and public names in package modules. The rest are decided by the Investigator's rules, as in `no_research`; the Explorer still writes its brief. Experiment label `agentic-adaptive` |

## 17. Contract changes (all additive)

- `METHODS` gains `agentic`; `CATEGORIES` gains the five line-level categories; `ACTIONS` gains
  `edit_lines`.
- `run_sweep(..., method="agentic")` dispatches to the agent team.
- A new `agents` entry in `core.contracts.INTERFACES` (the runtime, board, cache, `clean_project`).

## 18. Built so far (Phases 1 and 2)

The runtime and a first version of every agent are in `src/cleansweep/agents/`:
deterministic where the job allows it (brief facts, baseline, detectors, packaging, edits,
checks, reports), with JSON ReAct steps for the Explorer's summary and the Investigator.
Details worth knowing:
- The Investigator can only make a candidate more cautious than its detector lane: an edit is
  applied only when the detector put it in the safe lane and the Investigator says "safe".
  Formatting items skip the investigation (the AST check decides), security items are always
  suggestions.
- Formatting is safe only where the project enforces a formatter: the Explorer records in the
  brief whether `.pre-commit-config.yaml` or a CI config (GitHub workflows, GitLab, CircleCI,
  Azure) runs `ruff format` or `black`. Without one, formatting goes to the suggest lane with the
  reason "the project doesn't enforce a formatter" (a hand-formatted file is a choice, not
  slop). When the CI command names paths (`ruff format --check src/ tests/`), only files under
  them are safe; others are suggested ("the project's formatter check runs only on src, tests").
  `core.agents.format_policy: always` restores the old rule; the toy and demo runs use it,
  because their answer keys count the toy repo's formatting change as safe.
- A leftover file that is package data (a non-Python file in a folder of an importable package,
  next to at least two files of its type, such as one workflow preset among 68 YAML files) is
  only suggested: such files are loaded by name or by listing the folder, so "nothing imports
  it" proves nothing.
- Work packages group a file's edits of the same risk tier (at most `max_package`, default 4);
  formatting goes last in its own package, checked by AST equality. A package that fails with
  several edits is split in half (as v1's bisection does); a single edit gets at most 2 repair
  turns, else it is rolled back and a lesson is written.
- After a rollback, the Manager steps back to PLAN when later packages depend on the rolled-back
  one or a new lesson fits them; the Planner moves those items to the suggest lane, citing the
  lesson. If the final suite is worse than the baseline, the Manager steps back to EXECUTE and
  the Engineer reverts packages from the last one, rebuilding the branch without them.
- The delivered branch is built with `git commit-tree` from the workspace tree after each kept
  package, so the workspace's internal checkpoints never reach it.
- Agent turns are timed per role; an agent that raises ends the run cautiously (its package is
  rolled back) and the run still ends with a report.

Phase 2 added the line-level detectors (section 9), coverage-guided probes (section 11), a
prompt file per agent (`agents/prompts/`; the rule-based agents' files state their rules and are
their profiles in the event log), the Fixer's own system prompt for repairs, and fixes from the
first real-model runs (a thread-safe LLM reply cache, per-candidate isolation of investigations,
budget charges that check only their own limit, the Investigator's first checks run before the
LLM is asked, and a last-step nudge). Phase 3b added the UI snapshot check for Textual apps;
Phase 4 the `single_agent` ablation.

## 19. Risks

- Voyager latency: a run with many candidates is many sequential requests. Mitigations: budgets,
  parallel Investigators, deterministic tools, cached replies for repeat runs.
- LLM judgment varies between models and runs; the checks, not the agents' opinions, decide
  what is kept.
- Real projects may need data, a GPU or the network for their tests; the baseline records what
  runs, and the rule is never to weaken it.
