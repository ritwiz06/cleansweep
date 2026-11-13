#!/usr/bin/env bash
# Install the pre-push hook: ruff, the offline tests and the contract check run before every
# push, the same three checks as CI.
#
#   bash scripts/tools/install_hooks.sh
#
# The hook lives in .git/hooks, so it is never committed. An existing pre-push hook that this
# script did not write is left alone.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
hooks="$(git rev-parse --git-path hooks)"
hook="$hooks/pre-push"
marker="# written by scripts/tools/install_hooks.sh"
if [ -e "$hook" ] && ! grep -qF "$marker" "$hook"; then
  echo "install_hooks: $hook exists and was not written by this script; left as it is" >&2
  exit 1
fi
mkdir -p "$hooks"
cat > "$hook" <<HOOK
#!/usr/bin/env bash
$marker
HOOK
cat >> "$hook" <<'HOOK'
cd "$(git rev-parse --show-toplevel)" || exit 1
# git exports these to hooks; tests that run git in temp folders would otherwise write here
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_PREFIX
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
echo "pre-push: ruff, the offline tests and the contract check..." >&2
if "$PY" -m ruff check . &&
   "$PY" -m pytest -q -m "not llm and not docker and not network and not slow" &&
   "$PY" scripts/tools/check_contracts.py; then
  exit 0
fi
echo "pre-push: a check failed, so the push is blocked. Fix it and push again." >&2
exit 1
HOOK
chmod +x "$hook"
echo "installed $hook"
