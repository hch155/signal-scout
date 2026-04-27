#!/usr/bin/env bash
set -euo pipefail

# Downloads standalone build tools (no Node.js required).
# Run from project root: bash scripts/download-tools.sh
#
# Audit fix H-NEW-3 (2026-04-27): every downloaded binary is verified
# against a pinned SHA-256 before being made executable. A compromised
# upstream (namespace takeover, mirror MITM, malicious release) would
# fail verification and the build aborts. The previous unverified
# `curl | install` shape would silently inject attacker code into
# every developer + CI build, and from there into the bundled CSS / JS
# that ships to every user.
#
# Adding a new platform: download the binary once on that platform,
# compute `shasum -a 256` of the result, and add the value below
# under TW_SHA256 / ES_SHA256. CI / unfamiliar platforms will warn
# loudly when the pin is missing.

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

# Pinned SHA-256 hashes per (tool, platform). Computed locally with
# `shasum -a 256 <binary>`. Add new entries when supporting more
# platforms. Empty / missing entry → warning, not failure (lets new
# contributors bring up the build, but flags the integrity gap).
TW_PIN_KEY="${TW_OS}-${TW_ARCH}"
ES_PIN_KEY="${ES_OS}-${ES_ARCH}"

tw_expected_sha() {
  case "$1" in
    macos-arm64) echo "a1d0c7985759accca0bf12e51ac1dcbf0f6cf2fffb62e6e0f62d091c477a10a3" ;;
    *) echo "" ;;
  esac
}

es_expected_sha() {
  case "$1" in
    darwin-arm64) echo "6820034f50c56ec43c5bce2d71583ab0923e55b11476841c0424173f889044a9" ;;
    *) echo "" ;;
  esac
}

verify_sha256() {
  local label="$1" file="$2" expected="$3"
  local actual
  actual=$(shasum -a 256 "$file" | awk '{print $1}')
  if [ -z "$expected" ]; then
    echo "  ⚠️  WARNING: no SHA-256 pin for ${label}; got ${actual}"
    echo "      add it to scripts/download-tools.sh to lock this platform."
    return 0
  fi
  if [ "$expected" != "$actual" ]; then
    echo "  ❌ ERROR: SHA-256 mismatch for ${label}"
    echo "      expected: ${expected}"
    echo "      actual:   ${actual}"
    rm -f "$file"
    return 1
  fi
  echo "  ✓ SHA-256 verified (${label})"
}

# --- Tailwind CSS standalone CLI ---
TW_BIN="$TOOLS_DIR/tailwindcss"
if [ -x "$TW_BIN" ]; then
  echo "tailwindcss already exists, skipping download"
else
  TW_URL="https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-${TW_OS}-${TW_ARCH}"
  echo "Downloading tailwindcss v${TAILWIND_VERSION} (${TW_OS}-${TW_ARCH})..."
  curl -fsSL -o "$TW_BIN" "$TW_URL"
  verify_sha256 "tailwindcss-v${TAILWIND_VERSION}-${TW_PIN_KEY}" "$TW_BIN" "$(tw_expected_sha "$TW_PIN_KEY")"
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
  verify_sha256 "esbuild-v${ESBUILD_VERSION}-${ES_PIN_KEY}" "$ES_BIN" "$(es_expected_sha "$ES_PIN_KEY")"
  chmod +x "$ES_BIN"
  rm -rf "$TMP_DIR"
  echo "  -> $ES_BIN"
fi

echo ""
echo "Tools ready:"
"$TW_BIN" --help 2>&1 | head -1 || true
"$ES_BIN" --version || true
