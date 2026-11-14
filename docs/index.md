# Documentation

Start with the [README](../README.md): what CleanSweep does, how to install it, the quick start,
the results in brief and the known limitations. The documents below go deeper.

Project phases: Phase 1 = release v1.0, Phase 2 = v2.0–v2.1, Phase 3 = v3.0 (git tags).

**[User guide](user_guide.md).** How to clean your own project with `cleansweep clean`, read and
apply its result, keep per-project settings in `.cleansweep.yaml`, watch a repository, and use
Studio, with screenshots of its screens.

**[Studio design](studio_design.md).** The rules every Studio screen follows: the type and
spacing scales, the colors and glyphs of each item state in light and dark, the agent icons,
motion and reduced motion, and legibility at 1280×720 on a projector.

**[Architecture](architecture.md).** The Phase 1 pipeline (`method=cleansweep`):
open → analyze → plan → rank → batch → guard → report. What each package does, the contracts
between packages (`core/models.py`, `core/contracts.py`), the events and every setting.

**[Agentic design](agentic_design.md).** The agent team (Phase 2) behind `cleansweep clean`
and `method=agentic`: how it adapts AutoData's manager, squads and OHCache to code cleanup, the
Manager's phases, the 10 agents and their budgets, the message board and artifact cache,
lessons, coverage-guided probes, the safety rules, the command line and the ablations.

**[SlopBench data card](slopbench.md).** The slop-injection benchmark: what a seed plants, how it
is scored, the repositories at commits and their licenses; no third-party code is copied.

**[Pre-registration (Phase 3)](preregistration_v3.md).** The Phase 3 hypotheses H1–H4 with their metrics,
tests and thresholds, the run sizes, the limits every method gets, the hold-out and replacement
rules and the freeze, fixed before the first main run; later changes are dated deviations.

**[Requirements](requirements.md).** The acceptance checklists for Phase 2 (R1–R16, met) and Phase 3
(R17–R30): each requirement, the test that accepts it, its evidence and its status. A release is
made only when every row of its checklist passes.

**[Experiments](experiments.md).** For every experiment: the command, the commit it ran at, its
inputs and outputs, the models, runtime and data needs, and which script writes each committed
table. `scripts/reproduce_tables.sh` rebuilds the aggregate tables offline.

**[Results](results.md).** The full Phase 1 results: SWE-bench Tier 1 and Tier 2, the AIDev
repositories, Guard strength, the one-shot breakages, the Reviewer policies, the Scheduler and
the ranker, with confidence intervals and paired tests. Then Phase 2: the agent team against the Phase 1 pipeline on
every target set, the slop-injection benchmark, the ablations, probe strength, the Manager
scenarios, the case studies with LLM-reviewer acceptance, detection and watch.

**[Repository layout](repo_layout.md).** Every folder and what it is for: the package,
Studio, the demo, the scripts by purpose, the committed results, the data splits and the
tests.

**[Changelog](../CHANGELOG.md).** Every release and what changed in it.

**[Team pack](team/README.md).** For the four of us: start with the two-page
[handoff](team/handoff.md), then setup on macOS, Windows and Linux, a guided tour, the project
status, each member's tasks, how to contribute, the talk plan and the contribution log.
