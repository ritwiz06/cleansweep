#!/bin/bash
# The diff audit as a light job beside injected runs in a frozen clone: every hour, copy the
# clone's injected project folders whose methods have all finished (10 on seeds 1 and 2, 3 on
# seed 3) into this repository's results/raw/inject/ (once each), then run the audit over the
# new kept code edits; a last pass when no `exp_inject.py run` is left.
#   scripts/experiments/v2/audit_loop.sh ../cleansweep-runs-v2c [AUDIT_CLONE]
# AUDIT_CLONE (default: this repository) runs the audit, so a frozen copy of the code can do it
# while this checkout changes branches. The log is results/raw/diff_audit/audit_loop.log.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
RUNS=$(cd "$1" && pwd)
AUDIT=$(cd "${2:-$REPO}" && pwd)
LOG=$REPO/results/raw/diff_audit/audit_loop.log
PY=${PYTHON:-$REPO/.venv/bin/python}
mkdir -p "$(dirname "$LOG")"
pass_once() {
  for d in "$RUNS"/results/raw/inject/*-s*; do
    n=$(basename "$d")
    [ -f "$d/key.json" ] || continue
    want=10
    case "$n" in *-s3) want=3 ;; esac
    have=$(find "$d" -maxdepth 1 -name "*.json" ! -name key.json | wc -l)
    if [ "$have" -ge "$want" ] && [ ! -e "$REPO/results/raw/inject/$n" ]; then
      cp -R "$d" "$REPO/results/raw/inject/$n" && echo "$(date) copied inject/$n" >> "$LOG"
    fi
  done
  (cd "$AUDIT" && PYTHONPATH="$AUDIT/src:$AUDIT" "$PY" scripts/experiments/v2/exp_diff_audit.py run >> "$LOG" 2>&1)
  rc=$?
  echo "$(date) exp_diff_audit.py run exit $rc" >> "$LOG"
}
echo "$(date) start (runs $RUNS, audit $(git -C "$AUDIT" rev-parse --short HEAD))" >> "$LOG"
while pgrep -f "exp_inject.py run" > /dev/null; do
  pass_once
  sleep 3600
done
pass_once
echo "$(date) done" >> "$LOG"
