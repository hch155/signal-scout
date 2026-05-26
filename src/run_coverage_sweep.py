"""In-image CLI wrapper for the coverage-alert sweep.

Lives in `src/` so it ships in the Docker image (the dev-side
`scripts/coverage_alert_run.py` is intentionally `.dockerignore`d).
Invoked from inside the prod container:

    docker exec signal-scout-prod python run_coverage_sweep.py --verbose

Same flags as the dev script (--dry-run, --user-id N, --verbose).
Same exit semantics: returns 1 if any per-location processing
raised, 0 otherwise. The CI coverage-sweep job interprets the
exit code; a non-zero turns the job red and fires
CoverageSweepErrored.
"""
from __future__ import annotations

import argparse
import logging
import sys

from app import app
from coverage_alerts import run_coverage_alert_sweep

logger = logging.getLogger('run_coverage_sweep')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help="Compute diffs + log, but do not send emails or update snapshots.")
    ap.add_argument('--user-id', type=int, default=None,
                    help="Process only the UserLocation rows of this user_id.")
    ap.add_argument('--verbose', action='store_true',
                    help="Log every location, not just the ones that produced an email.")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )

    with app.app_context():
        counts = run_coverage_alert_sweep(
            dry_run=args.dry_run,
            user_id=args.user_id,
            verbose=args.verbose,
        )

    logger.info(
        "DONE (%s): %d processed | first-run=%d no-change=%d sent=%d send-failed=%d skipped=%d error=%d",
        'DRY-RUN' if args.dry_run else 'LIVE',
        counts['total_processed'],
        counts['first-run'], counts['no-change'],
        counts['sent'], counts['send-failed'], counts['skipped'],
        counts.get('error', 0),
    )
    return 1 if counts.get('error', 0) > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
