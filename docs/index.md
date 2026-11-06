# Documentation

Start with the [README](../README.md): what CleanSweep does, how to install it, the quick start,
the results in brief and the known limitations. The documents below go deeper.

**[User guide](user_guide.md).** How to clean your own project with `cleansweep clean`, read and
apply its result, keep per-project settings in `.cleansweep.yaml`, watch a repository, and use
Studio, with screenshots of its screens.

**[Architecture](architecture.md).** CleanSweep v1, the sweep pipeline (`method=cleansweep`):
open → analyze → plan → rank → batch → guard → report. What each package does, the contracts
between packages (`core/models.py`, `core/contracts.py`), the events and every setting.

**[Agentic design](agentic_design.md).** CleanSweep v2, the agent team behind `cleansweep clean`
and `method=agentic`: how it adapts AutoData's manager, squads and OHCache to code cleanup, the
Manager's phases, the 10 agents and their budgets, the message board and artifact cache,
lessons, coverage-guided probes, the safety rules, the command line and the ablations.

**[Requirements](requirements.md).** The acceptance checklists for v2.0 (R1–R16, met) and v3.0
(R17–R30): each requirement, the test that accepts it, its evidence and its status. A release is
made only when every row of its checklist passes.

**[Experiments](experiments.md).** For every experiment: the command, the commit it ran at, its
inputs and outputs, the models, runtime and data needs, and which script writes each committed
table. `scripts/reproduce_tables.sh` rebuilds the aggregate tables offline.

**[Results](results.md).** The full v1 results: SWE-bench Tier 1 and Tier 2, the AIDev
repositories, Guard strength, the one-shot breakages, the Reviewer policies, the Scheduler and
the ranker, with confidence intervals and paired tests. Then v2: the agent team against v1 on
every target set, the slop-injection benchmark, the ablations, probe strength, the Manager
scenarios, the case studies with LLM-reviewer acceptance, detection and watch.

**[Repository layout](repo_layout.md).** Every folder and what it is for: the package,
Studio, the demo, the scripts by purpose, the committed results, the data splits and the
tests.

**[Changelog](../CHANGELOG.md).** Every release and what changed in it.
