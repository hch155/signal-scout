"""OpenAPI / Swagger setup.

PR #6 documents the public read API (stations, find_station, search_stations,
submit_location). It does NOT document the internal HTML pages, /healthz,
/metrics, /account/*, /register, /login, /logout — those are not part of
the API contract and should not show up in the UI a paying client sees.

Design:
- All public API routes also register under /api/v1/<route> aliases. The
  legacy unprefixed paths stay as back-compat (browser JS still calls them).
  This lets us version the API without breaking existing callers.
- flasgger generates spec from per-route YAML docstrings and serves Swagger
  UI at /api/v1/docs and the spec at /api/v1/openapi.json.
- Spec declares two security schemes: ApiKeyAuth (X-API-Key header) and
  BrowserSession (cookies via /login). Both work — see require_api_access.

Why not flask-smorest / apispec? Both require Marshmallow schemas which is
a refactor we don't want now. Per-route YAML docstrings are good-enough at
this size and trivially upgradable later.
"""

from __future__ import annotations

from flasgger import Swagger
from flask import Flask


SWAGGER_TEMPLATE: dict = {
    "openapi": "3.0.3",
    "info": {
        "title": "Signal-Scout Public API",
        "description": (
            "Find the nearest cellular base stations across Poland.\n\n"
            "**Authentication.** All read endpoints accept either:\n"
            "* `X-API-Key: <token>` header — generate one at "
            "[/account](/account) after signing up. Higher rate limit, "
            "bypasses the same-origin Referer check.\n"
            "* A same-origin browser request — when JS on signal-scout.com "
            "calls these endpoints, the browser's `Referer` header is "
            "trusted and no key is needed.\n\n"
            "Calls without either are rejected with `403 access_denied`.\n\n"
            "**Rate limits.** 10 req/min for anonymous (Referer-only); "
            "60 req/min for `free` tier API keys; 300 req/min for `pro`; "
            "3000 req/min for `enterprise`. Tier shown on /account.\n\n"
            "**Coverage.** Polish national coordinates only "
            "(49.0–55.5° N, 14.0–24.2° E). Out-of-bounds requests get "
            "`400 Coordinates outside supported area`."
        ),
        "version": "1.0.0",
        "contact": {
            "email": "hcylwik@gmail.com",
        },
        "license": {
            "name": "Proprietary",
        },
    },
    # Filled in by init_api_docs() based on ENV — in prod we don't want
    # to dangle "http://127.0.0.1:8080" in front of public users.
    "servers": [],
    "components": {
        "securitySchemes": {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": (
                    "Personal API key from /account. Bypasses the same-origin "
                    "Referer check and grants higher rate limits per tier."
                ),
            },
            "BrowserSession": {
                "type": "apiKey",
                "in": "cookie",
                "name": "session",
                "description": (
                    "Set by POST /login. Used implicitly by browser fetch() "
                    "calls; not intended for programmatic clients."
                ),
            },
        },
        "schemas": {
            "Station": {
                "type": "object",
                "required": ["basestation_id", "latitude", "longitude",
                             "service_provider"],
                "properties": {
                    "basestation_id": {"type": "string", "example": "T1234"},
                    "city":           {"type": "string", "example": "Warszawa"},
                    "location":       {"type": "string", "example": "Złota 44, 39"},
                    "service_provider": {
                        "type": "string",
                        "example": "Orange Polska S.A.",
                        "enum": [
                            "Orange Polska S.A.",
                            "P4 sp. z o.o.",
                            "Polkomtel sp. z o.o.",
                            "T-Mobile Polska S.A.",
                        ],
                    },
                    "latitude":  {"type": "number", "format": "double", "example": 52.23083},
                    "longitude": {"type": "number", "format": "double", "example": 21.00083},
                    "frequency_bands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "example": ["5G2100", "LTE2600", "LTE1800", "GSM1800"],
                    },
                    "distance": {
                        "type": "number", "format": "double",
                        "description": "Great-circle distance from query point in km",
                        "example": 0.11,
                    },
                },
            },
            "StationsResponse": {
                "type": "object",
                "required": ["count", "stations"],
                "properties": {
                    "count": {"type": "integer", "example": 3},
                    "stations": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/Station"},
                    },
                },
            },
            "Error": {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        },
    },
    "security": [
        {"ApiKeyAuth": []},
        {"BrowserSession": []},
    ],
    "tags": [
        {
            "name": "Stations",
            "description": "Search the BTS dataset.",
        },
        {
            "name": "System",
            "description": "Liveness / introspection.",
        },
    ],
}


SWAGGER_CONFIG: dict = {
    "headers": [],
    "specs": [
        {
            "endpoint": "openapi_v1",
            "route": "/api/v1/openapi.json",
            "rule_filter": lambda rule: rule.endpoint.startswith("api_v1_"),
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/api/v1/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api/v1/docs/",
    "openapi": "3.0.3",
    # Hide the "Try it out" Authorize button's persistAuthorization tickle —
    # Swagger UI v5 default is good. We just want a clean look.
    "uiversion": 3,
}


def init_api_docs(app: Flask) -> Swagger:
    """Register flasgger on the app.

    Picks the `servers` list per-environment so the dropdown only shows
    targets that actually make sense from the page the user is on:
    - PRODUCTION: prod Cloud Run URL (+ apex once domain mapping is done)
    - non-prod : Local dev so a developer running 127.0.0.1:8080 can
      hit "Try it out" against their own instance.
    """
    import os
    is_prod = (os.getenv('ENV') or '').upper() == 'PRODUCTION'
    template = dict(SWAGGER_TEMPLATE)
    if is_prod:
        template['servers'] = [
            {"url": "https://signal-scout.run.app",
             "description": "Production (Cloud Run)"},
            # Apex (signal-scout.com) is currently a path-stripping 302 →
            # only useful as a target after Cloud Run Domain Mapping lands
            # (see ROADMAP). Re-enable then.
        ]
    else:
        template['servers'] = [
            {"url": "http://127.0.0.1:8080", "description": "Local dev"},
        ]
    return Swagger(app, template=template, config=SWAGGER_CONFIG)
