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

JS_FILES=(common compass map-initialization tips-interactions ui-interactions)

for name in "${JS_FILES[@]}"; do
  "$ES_BIN" \
    "$JS_SRC_DIR/${name}.js" \
    --outfile="$JS_DIST_DIR/${name}.min.js" \
    --minify \
    --drop:console \
    --sourcemap \
    --target=es2018

  SIZE=$(wc -c < "$JS_DIST_DIR/${name}.min.js" | tr -d ' ')
  echo "  -> ${name}.min.js: ${SIZE} bytes"
done

echo ""
echo "Build complete."
