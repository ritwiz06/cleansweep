#!/usr/bin/env bash
# Rebuild the aggregate tables and figures from the committed per-run CSVs, offline (no Docker,
# LLM or raw reports).
#
#   bash scripts/reproduce_tables.sh        # results/summary/ and results/figures/
#   bash scripts/reproduce_tables.sh DIR    # DIR/summary/ and DIR/figures/ instead
#
# v1: exp_tables.py: main_table, paired_tests, ablation, oneshot_series and the main figures,
# from main_results.csv and guard_strength.csv. exp_scheduler_tradeoff.py: scheduler_tradeoff.csv
# and its figure, from scheduler_replay.csv. v2: exp_tables_v2.py: eval_table, eval_paired,
# ablations, injection_summary and injection_summary_seeds12, from eval_runs.csv and
# injection.csv; exp_real_ablation.py table: real_ablation and real_ablation_tests, from
# real_ablation_runs.csv. On a clean checkout, `git status results/` shows no change afterwards.
# docs/experiments.md lists the per-run CSVs and the scripts that write them.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python}"
if [ $# -gt 0 ]; then
  CLEANSWEEP_RESULTS="$(cd "$1" && pwd)"
  export CLEANSWEEP_RESULTS
fi

"$PYTHON" scripts/experiments/v1/exp_tables.py > /dev/null
"$PYTHON" scripts/experiments/v1/exp_scheduler_tradeoff.py > /dev/null
"$PYTHON" scripts/experiments/v2/exp_tables_v2.py > /dev/null
"$PYTHON" scripts/experiments/v2/exp_real_ablation.py table > /dev/null
echo "reproduce_tables: rebuilt the tables and figures in ${CLEANSWEEP_RESULTS:-results}"
