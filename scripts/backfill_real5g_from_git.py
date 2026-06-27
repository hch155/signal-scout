"""Git-history replay for the Real-5G rollout tracker: extract every
historical stations.db blob from git history → write one n78 (3.5 GHz)
rollout snapshot per commit. A clone of replay_stats_history_from_git.py,
recomputing distinct 3.5 GHz site counts per operator/voivodeship from each
past stations.db.

real_5g_rollout reads stations.db directly (read-only sqlite), so each
historical blob is extracted to a temp file and aggregated in-process — no
ORM file-swap / fresh-interpreter dance per commit. maybe_write_real5g_snapshot
dedupes on snapshot_key (data_date) so re-running is harmless.

Run from the repo root:
    venv/bin/python scripts/backfill_real5g_from_git.py
"""
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MONTH_NAMES = {
    'january': '01', 'february': '02', 'march': '03', 'april': '04',
    'may': '05', 'june': '06', 'july': '07', 'august': '08',
    'september': '09', 'october': '10', 'november': '11', 'december': '12',
}


def parse_date_from_message(msg: str) -> str | None:
    """Heuristic — best-effort. Falls back to None if unparseable (caller
    uses commit-author-date as the snapshot key)."""
    m = msg.lower()
    dot = re.search(r'(\d{2})[.\-](\d{4})', m)
    if dot:
        mm, yyyy = dot.group(1), dot.group(2)
        return f"{yyyy}-{mm}-25"
    for name, mm in MONTH_NAMES.items():
        if name in m:
            yr = re.search(r'(20\d{2})', m)
            if yr:
                return f"{yr.group(1)}-{mm}-25"
    return None


def list_db_commits():
    out = subprocess.check_output(
        ['git', 'log', '--all', '--format=%H|%ai|%s',
         '--', 'src/instance/stations.db'],
        cwd=REPO, text=True,
    )
    rows = []
    for line in out.splitlines():
        sha, iso, msg = line.split('|', 2)
        rows.append((sha, iso, msg))
    return rows


def extract_db_blob(sha: str, dest: Path) -> bool:
    """`git show sha:path` → dest. Returns False on failure (e.g. the file
    didn't exist at that commit)."""
    try:
        with open(dest, 'wb') as out:
            subprocess.check_call(
                ['git', 'show', f'{sha}:src/instance/stations.db'],
                cwd=REPO, stdout=out,
            )
        return dest.stat().st_size > 1024
    except subprocess.CalledProcessError:
        return False


def main():
    print(f"Real-5G git-history replay started {datetime.utcnow().isoformat()}Z\n",
          flush=True)

    os.environ.setdefault("SECRET_KEY", "x" * 64)
    sys.path.insert(0, str(REPO / "src"))
    from app import app  # noqa: E402
    from real5g_rollout import (  # noqa: E402
        maybe_write_real5g_snapshot, real_5g_rollout,
    )
    users_db_path = str(REPO / "src" / "instance" / "users.db")

    rows = list_db_commits()
    seen_dates: set[str] = set()
    with app.app_context():
        for sha, author_iso, msg in rows:
            date_iso = parse_date_from_message(msg) or author_iso[:10]
            if date_iso in seen_dates:
                continue
            seen_dates.add(date_iso)
            print(f"\n=== {date_iso} ({sha[:7]}): {msg[:60]} ===", flush=True)
            with tempfile.NamedTemporaryFile(suffix='.db') as tmp:
                if not extract_db_blob(sha, Path(tmp.name)):
                    print("  SKIP — could not extract blob", flush=True)
                    continue
                rollout = real_5g_rollout(tmp.name)
            wrote = maybe_write_real5g_snapshot(
                users_db_path, date_iso, rollout,
                recorded_at_override=f"{date_iso}T20:00:00Z",
            )
            print(f"  wrote={wrote} total={rollout['total_sites']} "
                  f"operators={len(rollout['by_operator'])}", flush=True)

    print("\nDONE", flush=True)


if __name__ == '__main__':
    main()
