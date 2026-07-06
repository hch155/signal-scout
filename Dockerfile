# syntax=docker/dockerfile:1.7

# ── Builder ──
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# ── Runtime ──
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/usr/src/app/src
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends wget tini \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --system --create-home --uid 1000 --shell /usr/sbin/nologin appuser
RUN mkdir -p /var/lib/signal-scout/sessions \
    && chown -R appuser:appuser /var/lib/signal-scout
ENV SESSION_FILE_DIR=/var/lib/signal-scout/sessions
WORKDIR /usr/src/app
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels
COPY --chown=appuser:appuser . .
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", \
     "--workers=2", \
     "--preload", \
     "--timeout=30", \
     "--bind=0.0.0.0:8080", \
     "--access-logfile=-", \
     "--config=/usr/src/app/gunicorn_conf.py", \
     "app:app"]
