# syntax=docker/dockerfile:1.7

# Multi-stage build:
#   - builder: installs deps as wheels, runs as root, never reaches the
#     final image. C compiler / pip cache stay here.
#   - runtime: carries only Python + installed packages + app source. Runs
#     as non-root, has a HEALTHCHECK against /healthz (added in PR #3).
#
# Why: ~200MB smaller image, no compilers/headers in runtime → fewer Trivy
# CVE hits, faster Cloud Run cold starts, smaller attack surface.

# ── Builder ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# ── Asset builder ───────────────────────────────────────────────────────────
# 2026-05-16: regenerate minified JS+CSS during image build so source edits
# can't ship without re-minification. Avoids "src updated but dist/ stale"
# regression where Toggle Filters layout fix was in source but stale
# dist/pages/ui-interactions.min.js (Apr 29) shipped unchanged.
FROM debian:bookworm-slim AS asset-builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY src/static /src/src/static
COPY tailwind.config.js scripts/build.sh scripts/download-tools.sh /src/
COPY tools /src/tools/
RUN chmod +x /src/scripts/build.sh /src/scripts/download-tools.sh \
    && cd /src \
    && (test -x tools/esbuild && test -x tools/tailwindcss \
        || bash scripts/download-tools.sh) \
    && bash scripts/build.sh

# ── Runtime ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/usr/src/app/src

# wget for HEALTHCHECK; tini as PID 1 for clean signal handling under
# Gunicorn (Cloud Run sends SIGTERM on scale-down — without an init that
# reaps zombies, Gunicorn workers occasionally hang the shutdown for the
# default 30s grace period).
# `apt-get upgrade -y` pulls in security-fixed Debian packages that are
# newer than the base image's frozen snapshot — closes ~tens of HIGH/CRIT
# CVEs that Trivy flags on stale base images.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends wget tini \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Non-root user with a known UID so volume mounts behave consistently
# across hosts.
RUN useradd --system --create-home --uid 1000 --shell /usr/sbin/nologin appuser

# Writable session dir outside the read-only app source — flask-session
# needs to mkdir/write here. /tmp is a tmpfs on Cloud Run; using /var/lib
# instead so containers persist sessions across restarts on regular hosts
# (Cloud Run wipes either way).
RUN mkdir -p /var/lib/signal-scout/sessions \
    && chown -R appuser:appuser /var/lib/signal-scout
ENV SESSION_FILE_DIR=/var/lib/signal-scout/sessions

WORKDIR /usr/src/app

# Install pre-built wheels (no compiler in runtime stage).
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# App source last so code edits don't bust the dep-install layer cache.
COPY --chown=appuser:appuser . .

# Overlay fresh minified JS+CSS from asset-builder stage. The source-copied
# dist/ may be stale (build.sh wasn't run before docker build) — this
# guarantees the running image has freshly-minified assets matching the
# current src/static/scripts/pages/*.js. Fixes the "Toggle Filters layout
# fix shipped in source but old min.js still served" regression of 2026-05-16.
COPY --from=asset-builder --chown=appuser:appuser /src/src/static/dist /usr/src/app/src/static/dist
COPY --from=asset-builder --chown=appuser:appuser /src/src/static/css/output.css /usr/src/app/src/static/css/output.css

USER appuser

EXPOSE 8080

# Liveness probe consumed by Cloud Run / Kubernetes / Portainer. /healthz
# was added in PR #3 — does NOT touch the DB so a degraded DB doesn't
# trigger restart loops.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

# tini → gunicorn. --access-logfile=- routes access logs to stdout for
# Cloud Run / GCP logging ingest.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", \
     "--workers=2", \
     "--preload", \
     "--timeout=30", \
     "--bind=0.0.0.0:8080", \
     "--access-logfile=-", \
     "--config=/usr/src/app/gunicorn_conf.py", \
     "src.app:app"]
# --preload: import app ONCE in master before forking workers. Critical
# for SQLite + db.create_all() — without preload, every worker calls
# create_all in parallel and racing CREATE TABLE causes
# "table already exists" sqlite3.OperationalError → worker boot crash
# → intermittent 500s on prod.
