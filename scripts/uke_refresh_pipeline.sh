#!/usr/bin/env bash
# UKE -> stations.db rebuild, run INSIDE the refresh container after the repo is
# cloned (see deploy/db-refresh/). Downloads UKE, rebuilds + validates the DB,
# then commits and pushes to forgejo main (origin already carries the push token
# from the clone). Not meant to be run by hand on a workstation.
set -euo pipefail

retry() {
  local n=1
  until "$@"; do
    [ "$n" -ge 4 ] && { echo "FAILED after ${n}x: $*" >&2; return 1; }
    echo "retry ${n}: $*" >&2; sleep $((n * 15)); n=$((n + 1))
  done
}

export PYTHONPATH="$(pwd)/src"
retry python3 -m pip install --no-cache-dir -q -r requirements.txt openpyxl

prev="$(sqlite3 src/instance/stations.db 'SELECT COUNT(*) FROM base_station')"
echo "previous record count: ${prev}"

rm -f base_station_data/*.xlsx
retry python3 scripts/download_uke_data.py
python3 scripts/validate_db_update.py --step downloads
python3 scripts/stations_database_setup.py
python3 scripts/validate_db_update.py --step database --previous-count "${prev}"
python3 scripts/update_data_date.py

git config user.name  'db-refresh[bot]'
git config user.email 'db-refresh[bot]@example.local'
git add -A base_station_data src/instance/stations.db src/content/data.md
if git diff --cached --quiet; then
  echo 'No UKE changes this month — nothing to commit.'
  exit 0
fi
git commit -q -m "chore: database update $(LC_ALL=C date '+%B %Y')"
retry git push origin HEAD:main
echo 'stations.db refreshed + pushed to forgejo — CI will deploy.'
