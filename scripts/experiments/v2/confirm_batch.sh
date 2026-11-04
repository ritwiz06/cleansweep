#!/bin/bash
# The diff audit's targeted tests for the given edits (their test folders), one workspace at a
# time, as a detached light job; start and exit code go to results/raw/diff_audit/confirm.log.
#   nohup scripts/experiments/v2/confirm_batch.sh EDIT [EDIT ...] &
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
LOG=$REPO/results/raw/diff_audit/confirm.log
PY=${PYTHON:-$REPO/.venv/bin/python}
cd "$REPO" || exit 1
echo "$(date) start: $*" >> "$LOG"
"$PY" scripts/experiments/v2/exp_audit_confirm.py run --edits "$@" >> "$LOG" 2>&1
rc=$?
echo "$(date) exp_audit_confirm.py run exit $rc" >> "$LOG"
exit $rc
