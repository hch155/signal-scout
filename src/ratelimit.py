"""Tier-aware rate limiting for the public coverage API.

Flask-Limiter glue that turns the per-tier quotas defined in
``api_access.TIER_RATE_LIMITS`` (anonymous 10 / free 60 / pro 300 /
enterprise 3000 per minute) into a callable limit + callable key so quotas
are enforced **per API key** in shared Redis across every gunicorn worker
instead of N x per-IP per-worker.

Both callables read request state populated by ``require_api_access``
(``g.api_tier`` and ``g.api_key_user_id``), so the limiter decorator must sit
*inside* (below) ``@require_api_access`` on the route.

``assert_production_storage`` is the boot guard: ``memory://`` storage is
per-worker, so under a multi-worker fleet the effective limit is N x too
loose. The guard refuses to boot in PRODUCTION when the limiter is still on
``memory://``. The helpers are import-light and side-effect-free so they can
be unit-tested without the application database.
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import g, has_request_context
from flask_limiter.util import get_remote_address

logger = logging.getLogger(__name__)

DEFAULT_TIER = "anonymous"
MEMORY_STORAGE_SCHEME = "memory://"


def tier_limit_string() -> str:
    from api_access import get_tier_limit

    tier = (g.get("api_tier") if has_request_context() else None) or DEFAULT_TIER
    return get_tier_limit(tier)


def tier_key_func() -> str:
    if has_request_context():
        user_id = g.get("api_key_user_id")
        if user_id is not None:
            return f"api_key:{user_id}"
    return get_remote_address()


def is_memory_storage(storage_uri: Optional[str]) -> bool:
    uri = (storage_uri or "").strip().lower()
    return not uri or uri.startswith(MEMORY_STORAGE_SCHEME)


def production_storage_error(storage_uri: Optional[str], is_production: bool) -> Optional[str]:
    if is_production and is_memory_storage(storage_uri):
        return (
            "RATELIMIT_STORAGE_URI is memory:// in PRODUCTION. memory:// storage "
            "is per-worker, so under a multi-worker gunicorn fleet each worker "
            "keeps its own counters and the effective rate limit is N x too "
            "loose. Set RATELIMIT_STORAGE_URI to the shared redis:// backend."
        )
    return None


def assert_production_storage(
    storage_uri: Optional[str],
    is_production: bool,
    *,
    log: Optional[logging.Logger] = logger,
    strict: bool = True,
) -> None:
    message = production_storage_error(storage_uri, is_production)
    if message is None:
        return
    if log is not None:
        log.warning(message)
    if strict:
        raise RuntimeError(message)
