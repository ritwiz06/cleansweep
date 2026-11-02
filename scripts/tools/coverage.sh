#!/usr/bin/env bash
# Line coverage of the offline test suite on src/cleansweep/agents and src/cleansweep/guard
# (R10: at least 80%).
#
#   bash scripts/tools/coverage.sh      # the report, lowest first; exit 2 when under 80%
#
# The settings stay in a temporary rc file: a [tool.coverage] section in pyproject.toml would
# also apply where the probes run coverage inside a copy of this repository.
set -euo pipefail

cd "$(dirname "$0")/../.."
PYTHON="${PYTHON:-python}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/rc" <<EOF
[run]
source =
    src/cleansweep/agents
    src/cleansweep/guard
data_file = $tmp/.coverage

[report]
fail_under = 80
EOF

"$PYTHON" -m coverage run --rcfile="$tmp/rc" -m pytest -q -p no:cacheprovider \
  -m "not llm and not docker and not network and not slow"
"$PYTHON" -m coverage report --rcfile="$tmp/rc" --sort=cover
