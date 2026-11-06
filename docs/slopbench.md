# SlopBench data card

SlopBench is CleanSweep's slop-injection benchmark: known slop and traps planted into real Python
projects at a fixed seed, with a hidden behavior test the cleanup never sees. This card describes
what is released: the scripts and the list of repositories at commits. No third-party code is
copied or redistributed; anyone rebuilds the benchmark from the listed commits.

## What is released
- **Plant code:** `scripts/experiments/v2/exp_inject.py` (`inject`, the plant checks
  `check_plants`, the hidden test, `score`) and the v3 wrapper `scripts/experiments/v3/exp_inject_v3.py`.
- **Validator:** `exp_inject.py validate` re-runs the plant checks on prepared keys.
- **Repositories:** `results/summary/v3/slopbench_repos.csv`, written by
  `scripts/experiments/v3/slopbench.py list`: each repository's commit, license, clone URL and seeds.
  Nine come from v2's evaluation (seeds 1–3) and ten from v3's out-of-sample set (seed 4).

## What a seed plants
Into three of the project's own package modules, chosen by the seed: a leftover file, a dead
function, an exact duplicate, an unused import, a debug print, a commented-out block and an unused
dependency (the slop a cleanup should remove), and two traps it must keep: a near-duplicate that
rounds differently, and a framework callback (`ast.NodeVisitor.visit_Name`) reached only by name.
Every plant is checked before a run (used nowhere, the duplicate's copies match, the traps behave
differently from their removal), and the hidden test must pass on the injected project before
any cleanup, or the modules are drawn again (up to three times).

## How it is scored
Per category, the share of planted slop removed (recall) and the traps removed (precision against
the traps); the hidden test before and after the final diff, run in a network-less container.

## Licenses
Every v3 repository was screened for a license that allows local use (an allowlist of SPDX ids).
One v2 repository, thomasjjj/Telegram-Snowball-Sampling, has no license GitHub could detect; it is
listed with "none detected", and a user should check its terms before cloning it. SlopBench itself
redistributes no project code.

## Limits
The plants are simple and our own; seven slop kinds and two traps do not cover every way agents
leave slop. The hidden test checks only the planted code. The repositories come from AIDev
(Python projects with merged agent pull requests), so they are not a random sample of Python code.
