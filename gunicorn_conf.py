"""Gunicorn config — prometheus_client multiprocess support.

Without this, the 2-worker gunicorn fleet kept per-worker copies of
every Counter / Histogram / Gauge in process memory.
A /metrics scrape lands on a random worker → returns only that worker's
counter values → Prometheus sees the series jump up and down between
scrapes → `increase()` / `rate()` queries treat that as counter resets
and return 0 (or wrong rates).

Multiproc fix:
  - Each worker writes its counter state into PROMETHEUS_MULTIPROC_DIR
  - The /metrics view assembles a MultiProcessCollector across all
    workers' files → returns the SUM (correct cross-worker total)
  - On worker exit, mark its files dead so they're not double-counted
    after a fresh worker takes the same role

Required env at runtime:  PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
The directory is initialised + cleaned in observability.py (when_ready
would also work but the app-side init is more portable across
non-gunicorn dev runs).
"""
import os
import sys


access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s "%(f)s" "%(a)s"'


# 2026-04-29: TOP-LEVEL init. With gunicorn --preload, the app is
# imported in master BEFORE any lifecycle hook (on_starting/when_ready)
# fires — so a hook-based mkdir runs too late and the first Counter
# constructor crashes with FileNotFoundError. Top-level config-file
# code IS executed when --config is parsed, which happens before
# Arbiter.setup() / preload import. So we mkdir + clean here.
_MP_DIR = os.getenv("PROMETHEUS_MULTIPROC_DIR", "").strip()
if _MP_DIR:
    try:
        os.makedirs(_MP_DIR, exist_ok=True)
        for _fn in os.listdir(_MP_DIR):
            if _fn.endswith(".db"):
                try:
                    os.unlink(os.path.join(_MP_DIR, _fn))
                except OSError:
                    pass
        print(f"[prom-multiproc] init: {_MP_DIR} ready (cleaned stale files)",
              file=sys.stderr, flush=True)
    except OSError as _e:
        print(f"[prom-multiproc] init failed for {_MP_DIR}: {_e}",
              file=sys.stderr, flush=True)


from prometheus_client import multiprocess  # noqa: E402  (after env init)


def child_exit(server, worker):
    """Called in master after a worker exits. mark_process_dead writes
    a tombstone file so the multiproc collector can drop that worker's
    samples on the next /metrics scrape (otherwise we'd double-count
    a fresh worker that took the dead one's pid bucket)."""
    multiprocess.mark_process_dead(worker.pid)
