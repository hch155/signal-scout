#!/usr/bin/env bash
set -euo pipefail

# Downloads standalone build tools (no Node.js required).
# Run from project root: bash scripts/download-tools.sh

TAILWIND_VERSION="3.4.17"
ESBUILD_VERSION="0.24.2"

TOOLS_DIR="$(cd "$(dirname "$0")/.." && pwd)/tools"
mkdir -p "$TOOLS_DIR"

# Detect platform
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "$OS" in
  linux)  TW_OS="linux"  ; ES_OS="linux"  ;;
  darwin) TW_OS="macos"  ; ES_OS="darwin"  ;;
  *)      echo "Unsupported OS: $OS"; exit 1 ;;
esac

case "$ARCH" in
  x86_64)  TW_ARCH="x64"   ; ES_ARCH="x64"   ;;
  aarch64) TW_ARCH="arm64"  ; ES_ARCH="arm64"  ;;
  arm64)   TW_ARCH="arm64"  ; ES_ARCH="arm64"  ;;
  *)       echo "Unsupported arch: $ARCH"; exit 1 ;;
esac

# --- Tailwind CSS standalone CLI ---
TW_BIN="$TOOLS_DIR/tailwindcss"
if [ -x "$TW_BIN" ]; then
  echo "tailwindcss already exists, skipping download"
else
  TW_URL="https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-${TW_OS}-${TW_ARCH}"
  echo "Downloading tailwindcss v${TAILWIND_VERSION} (${TW_OS}-${TW_ARCH})..."
  curl -fsSL -o "$TW_BIN" "$TW_URL"
  chmod +x "$TW_BIN"
  echo "  -> $TW_BIN"
fi

# --- esbuild standalone binary ---
ES_BIN="$TOOLS_DIR/esbuild"
if [ -x "$ES_BIN" ]; then
  echo "esbuild already exists, skipping download"
else
  ES_PKG="@esbuild/${ES_OS}-${ES_ARCH}"
  ES_URL="https://registry.npmjs.org/${ES_PKG}/-/${ES_OS}-${ES_ARCH}-${ESBUILD_VERSION}.tgz"
  echo "Downloading esbuild v${ESBUILD_VERSION} (${ES_OS}-${ES_ARCH})..."
  TMP_DIR=$(mktemp -d)
  curl -fsSL "$ES_URL" | tar -xz -C "$TMP_DIR"
  cp "$TMP_DIR/package/bin/esbuild" "$ES_BIN"
  chmod +x "$ES_BIN"
  rm -rf "$TMP_DIR"
  echo "  -> $ES_BIN"
fi

echo ""
echo "Tools ready:"
"$TW_BIN" --help 2>&1 | head -1 || true
"$ES_BIN" --version || true
