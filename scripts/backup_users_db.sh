#!/usr/bin/env bash
# Hot backup of users.db (accounts, API keys, 2FA secrets — the only
# data in this system that cannot be rebuilt from public sources).
#
# Runs on the LXC that hosts the prod stack, against the bind-mounted
# DB file. Uses `sqlite3 .backup` (WAL-safe, consistent snapshot) —
# never `cp`, which can capture a torn page mid-checkpoint.
#
# Cron (the prod host, /etc/cron.d/signal-scout-backup):
#   0 * * * * root BACKUP_REMOTE=root@HOMELAB_LAN_IP:/opt/backups/signal-scout \
#     /opt/stacks/signal-scout-prod/backup_users_db.sh >> /var/log/signal-scout-backup.log 2>&1
#
# RPO: 1 h (hourly cron). RTO: minutes — see docs/runbook-backup-restore.md.

set -euo pipefail

DB="${USERS_DB:-/opt/stacks/signal-scout-prod/instance/users.db}"
DEST_DIR="${BACKUP_DIR:-/opt/backups/signal-scout}"
REMOTE="${BACKUP_REMOTE:-}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

command -v sqlite3 >/dev/null || { echo "ERROR: sqlite3 not installed" >&2; exit 1; }
[ -f "$DB" ] || { echo "ERROR: $DB not found" >&2; exit 1; }

mkdir -p "$DEST_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
out="$DEST_DIR/users-$stamp.db"

sqlite3 "$DB" ".backup '$out'"

check="$(sqlite3 "$out" 'PRAGMA integrity_check;')"
if [ "$check" != "ok" ]; then
    echo "ERROR: integrity_check failed on $out: $check" >&2
    rm -f "$out"
    exit 1
fi

gzip -f "$out"
echo "$(date -Is) backed up $(du -h "$out.gz" | cut -f1) -> $out.gz"

find "$DEST_DIR" -name 'users-*.db.gz' -mtime +"$RETENTION_DAYS" -delete

if [ -n "$REMOTE" ]; then
    rsync -az -e "ssh -o BatchMode=yes -o ConnectTimeout=10" \
        "$DEST_DIR/" "$REMOTE/"
    echo "$(date -Is) synced to $REMOTE"
fi
