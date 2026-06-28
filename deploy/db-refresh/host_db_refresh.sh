#!/usr/bin/env bash
#
# Monthly UKE -> stations.db refresh, run on the NUC host (where bip.uke.gov.pl
# AND the forgejo deploy server are both reachable — the LXC CI runner can reach
# neither path to UKE). Spins a throwaway python container on the HOST network,
# clones the repo with the push token, and runs scripts/uke_refresh_pipeline.sh
# inside it (download -> rebuild -> validate -> push to forgejo main). forgejo CI
# then deploys the committed DB. Driven by signal-scout-db-refresh.timer; the
# token comes from the systemd EnvironmentFile (/etc/signal-scout-db-refresh.env).
set -euo pipefail

: "${FORGEJO_TOKEN:?set FORGEJO_TOKEN (see /etc/signal-scout-db-refresh.env)}"
FORGEJO_HOST="${FORGEJO_HOST:-HOMELAB_LAN_IP:3000}"
REPO="${REPO:-hcylwik/signal-scout}"
IMAGE="${IMAGE:-docker.io/library/python:3.12-slim-bookworm}"

docker pull -q "$IMAGE" >/dev/null

exec docker run --rm --network host \
  -e FORGEJO_TOKEN="$FORGEJO_TOKEN" \
  -e FORGEJO_HOST="$FORGEJO_HOST" \
  -e REPO="$REPO" \
  -e GIT_TERMINAL_PROMPT=0 \
  -e DEBIAN_FRONTEND=noninteractive \
  "$IMAGE" bash -ceu '
    for i in 1 2 3 4; do
      apt-get update -qq && apt-get install -y -qq --no-install-recommends \
        git curl ca-certificates sqlite3 build-essential libsqlite3-dev && break
      echo "apt retry $i" >&2; sleep $((i * 15)); [ "$i" = 4 ] && exit 1
    done
    for i in 1 2 3 4; do
      git clone --depth 1 --branch main \
        "http://hcylwik:${FORGEJO_TOKEN}@${FORGEJO_HOST}/${REPO}.git" /tmp/repo && break
      echo "clone retry $i" >&2; sleep $((i * 15)); [ "$i" = 4 ] && exit 1
    done
    cd /tmp/repo
    exec bash scripts/uke_refresh_pipeline.sh
  '
