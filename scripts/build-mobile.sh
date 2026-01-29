#!/usr/bin/env bash
set -euo pipefail

# Syncs and builds the Capacitor mobile project.
# Run from project root: bash scripts/build-mobile.sh [ios|android|sync]
#
# Commands:
#   sync     Sync web assets and plugins to native projects (default)
#   ios      Sync + open Xcode
#   android  Sync + open Android Studio

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MOBILE_DIR="$ROOT_DIR/mobile"

if [ ! -d "$MOBILE_DIR/node_modules" ]; then
  echo "Installing mobile dependencies..."
  (cd "$MOBILE_DIR" && npm install)
fi

CMD="${1:-sync}"

echo "Syncing Capacitor projects..."
(cd "$MOBILE_DIR" && npx cap sync)

case "$CMD" in
  ios)
    echo "Opening Xcode..."
    (cd "$MOBILE_DIR" && npx cap open ios)
    ;;
  android)
    echo "Opening Android Studio..."
    (cd "$MOBILE_DIR" && npx cap open android)
    ;;
  sync)
    echo "Sync complete."
    echo ""
    echo "Next steps:"
    echo "  bash scripts/build-mobile.sh ios       # Open in Xcode"
    echo "  bash scripts/build-mobile.sh android    # Open in Android Studio"
    ;;
  *)
    echo "Unknown command: $CMD"
    echo "Usage: build-mobile.sh [sync|ios|android]"
    exit 1
    ;;
esac
