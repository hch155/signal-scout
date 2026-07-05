#!/usr/bin/env bash
# Out-of-band prod heartbeat canary for signal-scout.
#
# The whole point: this lives OUTSIDE the CI/CD pipeline's failure domain, so it
# catches the three failures every in-pipeline safeguard is blind to —
#   1. push -> no run (a run that never starts can't notify),
#   2. a silent no-op deploy (prod never advanced),
#   3. a "green" deploy serving OAuth/DB-broken code (/healthz stays 200).
# Run it on a different, always-on host (ideally wired) via the systemd timer.
#
# It only touches PUBLIC URLs + (optionally) the forge API, so it works even
# when the internal homelab network is flapping. Alerts go to a configurable
# webhook (ntfy / Slack / Discord / generic POST) and are always logged.
#
# Config (env, all optional except sensible defaults):
#   PROD_URL          default https://signal-scout.com
#   ALERT_WEBHOOK     URL to POST the alert body to (ntfy topic, Slack, …). Unset -> log only.
#   FORGE_API         e.g. https://forgejo.example.local/api/v1  (enables no-deploy detection)
#   FORGE_TOKEN       token for FORGE_API (read repo)
#   FORGE_REPO        owner/repo, default hcylwik/signal-scout
#   MAX_STALE_HOURS   alert if prod SHA != main SHA for longer than this (default 6)
#   STATE_DIR         default /var/lib/prod-canary
set -uo pipefail

PROD_URL="${PROD_URL:-https://signal-scout.com}"
FORGE_REPO="${FORGE_REPO:-hcylwik/signal-scout}"
MAX_STALE_HOURS="${MAX_STALE_HOURS:-6}"
STATE_DIR="${STATE_DIR:-/var/lib/prod-canary}"
mkdir -p "$STATE_DIR" 2>/dev/null || STATE_DIR="/tmp/prod-canary" && mkdir -p "$STATE_DIR"
STALE_FILE="$STATE_DIR/last_match_epoch"
now=$(date +%s)

log()   { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }
alert() {
  local msg="$1"
  log "ALERT: $msg"
  if [ -n "${ALERT_WEBHOOK:-}" ]; then
    curl -sS -m 15 -H "Title: signal-scout prod canary" \
      -d "signal-scout: $msg" "$ALERT_WEBHOOK" >/dev/null 2>&1 \
      || log "warn: alert webhook POST failed"
  fi
}

problems=()

# 1. Deep readiness: both DB binds must respond.
ready=$(curl -s -m 8 -o /dev/null -w '%{http_code}' "$PROD_URL/readyz")
[ "$ready" = "200" ] || problems+=("readyz=$ready (DB unreachable?)")

# 2. Liveness + version string.
health=$(curl -s -m 8 "$PROD_URL/api/v1/healthz")
ver=$(printf '%s' "$health" | sed -n 's/.*"version"[ ]*:[ ]*"\([^"]*\)".*/\1/p')
[ -n "$ver" ] || problems+=("no version in /healthz (app not serving?)")

# 3. OAuth must be live: /auth/google/login 302s to Google. This is the exact
#    check that caught nothing during the OAuth outage — /healthz stayed 200.
oauth=$(curl -s -m 8 -o /dev/null -w '%{redirect_url}' "$PROD_URL/auth/google/login")
echo "$oauth" | grep -q 'accounts.google.com' || problems+=("OAuth broken: /auth/google/login -> '${oauth:-<none>}'")

# 4. (optional) No-deploy detection: prod version SHA vs main HEAD SHA.
if [ -n "${FORGE_API:-}" ] && [ -n "${FORGE_TOKEN:-}" ]; then
  main_sha=$(curl -s -m 10 -H "Authorization: token $FORGE_TOKEN" \
    "$FORGE_API/repos/$FORGE_REPO/branches/main" \
    | sed -n 's/.*"id"[ ]*:[ ]*"\([0-9a-f]\{7\}\)[0-9a-f]*".*/\1/p' | head -1)
  prod_sha=$(printf '%s' "$ver" | grep -oE '[0-9a-f]{7}$')
  if [ -n "$main_sha" ] && [ -n "$prod_sha" ]; then
    if [ "$main_sha" = "$prod_sha" ]; then
      echo "$now" > "$STALE_FILE"
    else
      last=$(cat "$STALE_FILE" 2>/dev/null || echo "$now")
      hours=$(( (now - last) / 3600 ))
      if [ "$hours" -ge "$MAX_STALE_HOURS" ]; then
        problems+=("prod on $prod_sha but main is $main_sha for ${hours}h — deploy stuck? (push->no-run?)")
      else
        log "info: prod($prod_sha) behind main($main_sha) for ${hours}h (< ${MAX_STALE_HOURS}h grace)"
      fi
    fi
  fi
fi

if [ ${#problems[@]} -eq 0 ]; then
  log "OK: readyz=200 version=$ver oauth=up"
  exit 0
fi
alert "$(printf '%s; ' "${problems[@]}")(version=${ver:-?})"
exit 1
