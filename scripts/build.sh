#!/usr/bin/env bash
set -euo pipefail

# Builds all CSS and JS assets using standalone tools (no Node.js).
# Run from project root: bash scripts/build.sh
#
# Prerequisites: run `bash scripts/download-tools.sh` first.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS_DIR="$ROOT_DIR/tools"
TW_BIN="$TOOLS_DIR/tailwindcss"
ES_BIN="$TOOLS_DIR/esbuild"

# Verify tools exist
for bin in "$TW_BIN" "$ES_BIN"; do
  if [ ! -x "$bin" ]; then
    echo "ERROR: $bin not found. Run: bash scripts/download-tools.sh"
    exit 1
  fi
done

# ── CSS: Tailwind build (single minified output) ──
echo "Building CSS with Tailwind standalone CLI..."
"$TW_BIN" \
  -i "$ROOT_DIR/src/static/css/styles.css" \
  -o "$ROOT_DIR/src/static/css/output.css" \
  --config "$ROOT_DIR/tailwind.config.js" \
  --minify

CSS_SIZE=$(wc -c < "$ROOT_DIR/src/static/css/output.css" | tr -d ' ')
echo "  -> output.css: ${CSS_SIZE} bytes"

# ── JS: esbuild minification ──
echo "Minifying JS with esbuild..."

JS_SRC_DIR="$ROOT_DIR/src/static/scripts/pages"
JS_DIST_DIR="$ROOT_DIR/src/static/dist/pages"
mkdir -p "$JS_DIST_DIR"

JS_FILES=(common compass map-initialization tips-interactions ui-interactions account)

for name in "${JS_FILES[@]}"; do
  # PR #46.6: dropped --sourcemap. The .map files were generated but
  # NOT shipped in the Docker image, so devtools always 404'd on
  # `<file>.min.js.map` lookups (5 console errors per page load —
  # noise that drowns real errors). Local debugging can edit the raw
  # `.js` source under static/scripts/pages/ and skip min build, or
  # set BUILD_ENV=dev to opt back in:
  if [ "${BUILD_ENV:-}" = "dev" ]; then
    SOURCEMAP_FLAG="--sourcemap"
  else
    SOURCEMAP_FLAG=""
  fi
  # shellcheck disable=SC2086 # intentional unquoted expansion of optional flag
  "$ES_BIN" \
    "$JS_SRC_DIR/${name}.js" \
    --outfile="$JS_DIST_DIR/${name}.min.js" \
    --minify \
    --drop:console \
    $SOURCEMAP_FLAG \
    --target=es2018

  # Stale .map left over from previous --sourcemap builds: remove so
  # the dist dir matches the new (no-map) output.
  rm -f "$JS_DIST_DIR/${name}.min.js.map"

  SIZE=$(wc -c < "$JS_DIST_DIR/${name}.min.js" | tr -d ' ')
  echo "  -> ${name}.min.js: ${SIZE} bytes"
done

echo ""
echo "Build complete."
