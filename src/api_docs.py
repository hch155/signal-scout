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
            "bypasses the same-origin Origin/Referer check.\n"
            "* A same-origin browser request — when JS on signal-scout.com "
            "calls these endpoints, the browser's `Origin` or `Referer` "
            "header is trusted and no key is needed.\n\n"
            "Calls without either are rejected with `403 access_denied`.\n\n"
            "**Rate limits.** The address-coverage endpoints "
            "(`/coverage_by_address`, its `/batch`, `/coverage_card`) are "
            "tier-limited: 10 req/min for anonymous (browser, no key); "
            "60 req/min for `free` tier API keys; 300 req/min for `pro`; "
            "3000 req/min for `enterprise`. Tier shown on /account. "
            "Other read endpoints have fixed per-IP limits: 30 req/min on "
            "/stations, /search_stations, /submit_location and "
            "/coverage_gaps; 16 req/min otherwise.\n\n"
            "**Coverage.** Polish national coordinates only "
            "(49.0–55.5° N, 14.0–24.2° E). Out-of-bounds coordinates "
            "return HTTP 200 with `outside_pl: true` and an empty result "
            "set (only /embed/widget rejects them with "
            "`400 Coordinates outside supported area`)."
        ),
        "version": "1.0.0",
        "contact": {
            "email": "hcylwik@gmail.com",
        },
        "license": {
            "name": "Proprietary",
        },
    },
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
            "AddressMatch": {
                "type": "object",
                "required": ["display", "latitude", "longitude", "confidence",
                             "geocode_precision"],
                "properties": {
                    "display": {
                        "type": "string",
                        "example": "Złota 44, 00-120 Warszawa",
                    },
                    "latitude":  {"type": "number", "format": "double", "example": 52.23083},
                    "longitude": {"type": "number", "format": "double", "example": 21.00083},
                    "confidence": {
                        "type": "string",
                        "description": (
                            "Geocoder match quality. `low` typically means the "
                            "house number was dropped and a street-level "
                            "centroid was returned."
                        ),
                        "example": "exact",
                        "enum": ["exact", "high", "medium", "low"],
                    },
                    "geocode_precision": {
                        "type": "string",
                        "description": (
                            "`building` is an exact house-number hit; "
                            "`street_centroid` means the house number was "
                            "dropped and a street-level centroid was returned."
                        ),
                        "example": "building",
                        "enum": ["building", "street_centroid"],
                    },
                    "matched_on": {
                        "type": "string",
                        "description": "Raw query field the geocoder resolved against.",
                        "example": "Złota 44, Warszawa",
                    },
                    "alternatives": {
                        "type": "array",
                        "description": "Lower-ranked candidates for the same query.",
                        "items": {"$ref": "#/components/schemas/AddressMatch"},
                    },
                },
            },
            "OperatorCoverage": {
                "type": "object",
                "required": ["operator", "service_provider", "signal_tier",
                             "real_5g"],
                "properties": {
                    "operator": {
                        "type": "string",
                        "example": "Orange",
                        "enum": ["Orange", "Play", "Plus", "T-Mobile"],
                    },
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
                    "nearest_distance_km": {
                        "type": "number", "format": "double",
                        "nullable": True,
                        "description": "Distance to this operator's nearest station in km.",
                        "example": 0.73,
                    },
                    "signal_tier": {
                        "type": "string",
                        "nullable": True,
                        "example": "Good",
                        "enum": ["Excellent", "Good", "Fair", "Poor", None],
                    },
                    "technologies": {
                        "type": "object",
                        "description": (
                            "Presence flag per radio technology on this "
                            "operator's bands. `5G` is ANY 5G band (capacity "
                            "or coverage)."
                        ),
                        "additionalProperties": {"type": "boolean"},
                        "example": {"5G": True, "LTE": True, "GSM": True},
                    },
                    "real_5g": {
                        "type": "boolean",
                        "description": (
                            "True when this operator has a C-band 5G carrier "
                            "(>= 3400 MHz, e.g. 5G3500/5G3600) in range — real "
                            "capacity 5G, not low-band/DSS coverage 5G."
                        ),
                        "example": True,
                    },
                    "5g_bands_mhz": {
                        "type": "array",
                        "description": (
                            "Parsed centre frequencies (MHz) of this operator's "
                            "in-range 5G carriers, e.g. [3600, 2100, 700]."
                        ),
                        "items": {"type": "integer"},
                        "example": [3600, 2100, 700],
                    },
                },
            },
            "Coverage": {
                "type": "object",
                "required": ["signal_tier", "signal_score", "real_5g", "operators"],
                "properties": {
                    "signal_tier": {
                        "type": "string",
                        "nullable": True,
                        "description": (
                            "Best signal tier across all operators; null when "
                            "no masts fall within the search radius (then "
                            "`operators` is empty)."
                        ),
                        "example": "Good",
                        "enum": ["Excellent", "Good", "Fair", "Poor", None],
                    },
                    "signal_score": {
                        "type": "integer",
                        "description": "0–100 score derived from the nearest mast across all operators.",
                        "example": 72,
                    },
                    "real_5g": {
                        "type": "boolean",
                        "description": (
                            "True when any in-range operator offers a C-band "
                            "5G carrier (>= 3400 MHz)."
                        ),
                        "example": True,
                    },
                    "operators": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/OperatorCoverage"},
                    },
                },
            },
            "CoverageLabels": {
                "type": "object",
                "description": "Human-readable consumer layer (PL + EN) for a real-estate report.",
                "properties": {
                    "tier_pl": {
                        "type": "string",
                        "description": (
                            "Polish tier label: Poor->Niski, Fair->Średni, "
                            "Good->Dobry, Excellent->Bardzo dobry, no coverage "
                            "in radius->Brak zasięgu."
                        ),
                        "example": "Bardzo dobry",
                    },
                    "headline_pl": {
                        "type": "string",
                        "example": "Bardzo dobry zasięg · Prawdziwe 5G (3,5 GHz) dostępne",
                    },
                    "real_5g_pl": {
                        "type": "string",
                        "example": "Prawdziwe 5G (3,5 GHz)",
                        "enum": [
                            "Prawdziwe 5G (3,5 GHz)",
                            "Tylko 5G zasięgowe",
                            "Brak 5G",
                        ],
                    },
                    "tier_en": {
                        "type": "string",
                        "description": "English tier label mirroring the machine enum.",
                        "example": "Excellent",
                    },
                    "headline_en": {
                        "type": "string",
                        "example": "Excellent coverage · Real 5G (3.5 GHz) available",
                    },
                    "real_5g_en": {
                        "type": "string",
                        "example": "Real 5G (3.5 GHz)",
                        "enum": ["Real 5G (3.5 GHz)", "Coverage 5G only", "No 5G"],
                    },
                },
            },
            "CoverageDisclaimer": {
                "type": "object",
                "description": "Bilingual estimate caveat for the consumer report.",
                "required": ["pl", "en"],
                "properties": {
                    "pl": {"type": "string"},
                    "en": {"type": "string"},
                },
            },
            "CoverageByAddressResponse": {
                "type": "object",
                "required": ["query", "match", "coverage"],
                "properties": {
                    "query": {
                        "type": "string",
                        "example": "Złota 44, Warszawa",
                    },
                    "match": {"$ref": "#/components/schemas/AddressMatch"},
                    "coverage": {
                        "nullable": True,
                        "description": (
                            "Null when the matched point is outside PL bounds "
                            "(`outside_pl: true`)."
                        ),
                        "allOf": [{"$ref": "#/components/schemas/Coverage"}],
                    },
                    "outside_pl": {
                        "type": "boolean",
                        "description": (
                            "True when the matched point falls outside Poland; "
                            "`coverage` is then null and the label/disclaimer "
                            "fields are omitted."
                        ),
                        "example": False,
                    },
                    "labels": {"$ref": "#/components/schemas/CoverageLabels"},
                    "is_estimate": {
                        "type": "boolean",
                        "description": (
                            "True when geocoding fell back to a street/city "
                            "centroid, so coverage is approximate."
                        ),
                        "example": False,
                    },
                    "disclaimer": {"$ref": "#/components/schemas/CoverageDisclaimer"},
                    "data_date": {
                        "type": "string",
                        "format": "date",
                        "description": "Date of the underlying BTS dataset.",
                        "example": "2026-06-01",
                    },
                },
            },
            "CoverageByAddressBatchResult": {
                "type": "object",
                "required": ["id", "status"],
                "properties": {
                    "id": {
                        "type": "string",
                        "nullable": True,
                        "description": "Caller-supplied id echoed back for this row (null when omitted).",
                        "example": "row-1",
                    },
                    "status": {
                        "type": "string",
                        "example": "ok",
                        "enum": ["ok", "no_match", "ambiguous", "outside_pl", "error"],
                    },
                    "query": {
                        "type": "string",
                        "example": "Złota 44, Warszawa",
                    },
                    "match": {"$ref": "#/components/schemas/AddressMatch"},
                    "coverage": {"$ref": "#/components/schemas/Coverage"},
                    "labels": {"$ref": "#/components/schemas/CoverageLabels"},
                    "is_estimate": {"type": "boolean", "example": False},
                    "disclaimer": {"$ref": "#/components/schemas/CoverageDisclaimer"},
                },
            },
            "CoverageByAddressBatchResponse": {
                "type": "object",
                "required": ["count", "results"],
                "properties": {
                    "count": {"type": "integer", "example": 2},
                    "results": {
                        "type": "array",
                        "items": {
                            "$ref": "#/components/schemas/CoverageByAddressBatchResult"
                        },
                    },
                    "data_date": {
                        "type": "string",
                        "format": "date",
                        "description": "Date of the underlying BTS dataset.",
                        "example": "2026-06-01",
                    },
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
            "name": "Address",
            "description": "Geocode a Polish address and estimate mobile coverage.",
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
    "uiversion": 3,
}


def init_api_docs(app: Flask) -> Swagger:
    """Register flasgger on the app.

    Picks the `servers` list per-environment so the dropdown only shows
    targets that actually make sense from the page the user is on:
    - PRODUCTION: production + staging public hosts
    - STAGING:    staging public host
    - non-prod :  Local dev so a developer running 127.0.0.1:8080 can
                  hit "Try it out" against their own instance.
    """
    import os
    env = (os.getenv('ENV') or '').upper()
    template = dict(SWAGGER_TEMPLATE)
    if env == 'PRODUCTION':
        template['servers'] = [
            {"url": "https://signal-scout.com", "description": "Production"},
            {"url": "https://staging.signal-scout.com", "description": "Staging"},
        ]
    elif env == 'STAGING':
        template['servers'] = [
            {"url": "https://staging.signal-scout.com", "description": "Staging"},
        ]
    else:
        template['servers'] = [
            {"url": "http://127.0.0.1:8080", "description": "Local dev"},
        ]
    return Swagger(app, template=template, config=SWAGGER_CONFIG)
