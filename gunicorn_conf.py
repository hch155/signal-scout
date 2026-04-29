"""Gunicorn config — prometheus_client multiprocess support.

Without this, the 2-worker gunicorn fleet behind Cloud Run kept per-
worker copies of every Counter / Histogram / Gauge in process memory.
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
import shutil

from prometheus_client import multiprocess


def on_starting(server):
    """Called once in the master process before any workers are forked.
    Purge stale per-pid files from PROMETHEUS_MULTIPROC_DIR — Cloud
    Run's /tmp survives across worker recycles within the same
    instance, so dead-pid files would otherwise be re-counted into
    /metrics totals after a worker recycle. SAFE to delete here
    because no Counter/Histogram has been constructed yet."""
    d = os.getenv("PROMETHEUS_MULTIPROC_DIR", "").strip()
    if not d:
        return
    try:
        os.makedirs(d, exist_ok=True)
        for fn in os.listdir(d):
            if fn.endswith(".db"):
                try:
                    os.unlink(os.path.join(d, fn))
                except OSError:
                    pass
        server.log.info("[prom-multiproc] cleaned %s on master start", d)
    except OSError as e:
        server.log.warning("[prom-multiproc] cleanup of %s failed: %s", d, e)


def child_exit(server, worker):
    """Called in master after a worker exits. mark_process_dead writes
    a tombstone file so the multiproc collector can drop that worker's
    samples on the next /metrics scrape (otherwise we'd double-count
    a fresh worker that took the dead one's pid bucket)."""
    multiprocess.mark_process_dead(worker.pid)
