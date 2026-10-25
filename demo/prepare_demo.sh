#!/usr/bin/env bash
# Copy the demo app into a fresh git repo for the presentation.
#
#   bash demo/prepare_demo.sh                  # app only
#   bash demo/prepare_demo.sh --with-feature   # app + feature.patch (the agent's change)
#   bash demo/prepare_demo.sh [--with-feature] DEST
#
# Default DEST is $TMPDIR/cleansweep-demo (the Live sweep page offers it as a target).
# The answer key and the hidden tests are copied next to the app, so hidden checks and the
# outcome score work there too. Prints the path of the prepared app.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="${TMPDIR:-/tmp}"
DEST="${TMP%/}/cleansweep-demo"
WITH_FEATURE=0
for arg in "$@"; do
  case "$arg" in
    --with-feature) WITH_FEATURE=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) DEST="$arg" ;;
  esac
done

MARKER=".cleansweep-demo"
if [ -e "$DEST" ]; then
  if [ ! -f "$DEST/$MARKER" ]; then
    echo "prepare_demo: $DEST exists and was not made by this script; refusing to delete it" >&2
    exit 1
  fi
  rm -rf "$DEST"
fi
mkdir -p "$DEST"
touch "$DEST/$MARKER"

cp -R "$HERE/shop_app" "$DEST/shop_app"
cp -R "$HERE/shop_app_hidden" "$DEST/shop_app_hidden"
cp "$HERE/shop_app_expected.json" "$DEST/shop_app_expected.json"
find "$DEST" -name __pycache__ -prune -exec rm -rf {} +

cd "$DEST/shop_app"
G=(git -c user.name=demo -c user.email=demo@localhost -c core.hooksPath=/dev/null -c commit.gpgsign=false)
"${G[@]}" init -q
"${G[@]}" add -A
"${G[@]}" commit -q -m "bookshelf inventory app"
if [ "$WITH_FEATURE" = 1 ]; then
  "${G[@]}" apply "$HERE/feature.patch"
  "${G[@]}" add -A
  "${G[@]}" commit -q -m "add low-stock report"
fi
echo "$DEST/shop_app"
