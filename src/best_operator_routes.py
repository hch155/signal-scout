"""Best-operator consumer page + referral redirect, as a Flask blueprint.

Mirrors auth_routes.register_auth_routes: view functions are defined at
module scope, then register_best_operator_routes(app, limiter=...) wraps
them with rate limits and registers the blueprint. Dependencies that live
in app.py (_resolve_address_coverage, get_data_date, stations_db_path,
the coverage disclaimer, active-language lookup) are reached through the
app module captured at registration, avoiding a request-time re-import.

Routes:
- GET /best-operator?q=<address> — HTML page (and ?format=json for the JS
  fetch/render path) ranking operators for an address.
- GET /go/operator/<slug>       — bumps a Prometheus click counter, then
  302s to the configured affiliate URL so click-through is measurable.
"""

from __future__ import annotations

import logging
import sys

from flask import Blueprint, abort, jsonify, redirect, render_template, request

from prometheus_client import Counter

from best_operator import build_referral_url, has_referral, rank_operators


logger = logging.getLogger(__name__)

best_operator_bp = Blueprint("best_operator", __name__)

_app_module = None

referral_clicks_total = Counter(
    "signal_scout_best_operator_referral_clicks_total",
    "Best-operator referral CTA clicks, by operator slug.",
    labelnames=("operator",),
)

_MAX_QUERY_LEN = 120


def _too_few_letters(query: str) -> bool:
    return sum(ch.isalpha() for ch in query) < 3


def _serialize_operator(op: dict) -> dict:
    return {
        "operator": op.get("operator"),
        "slug": op.get("slug"),
        "signal_tier": op.get("signal_tier"),
        "nearest_distance_km": op.get("nearest_distance_km"),
        "real_5g": op.get("real_5g"),
        "real5g_km": op.get("real5g_km"),
        "technologies": op.get("technologies"),
        "5g_bands_mhz": op.get("5g_bands_mhz"),
        "rank_score": op.get("rank_score"),
        "recommended": op.get("recommended"),
        "rationale": op.get("rationale"),
        "referral_path": op.get("referral_path"),
    }


def _attach_referral_paths(operators: list) -> None:
    for op in operators:
        slug = op.get("slug")
        op["referral_path"] = f"/go/operator/{slug}" if has_referral(slug) else None


def best_operator_page():
    query = (request.args.get("q", type=str, default="") or "").strip()
    wants_json = request.args.get("format") == "json"
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)

    if lat is not None and lng is not None:
        try:
            outcome = _app_module._resolve_latlng_coverage(lat, lng)
        except Exception:
            logger.exception("best_operator_page latlng resolve failed")
            return jsonify({"status": "error", "operators": []}), 500
        if outcome["status"] == "outside_pl":
            return jsonify({"status": "outside_pl", "operators": []})
        operators = rank_operators(outcome.get("coverage") or {})
        _attach_referral_paths(operators)
        return jsonify({
            "status": "ok" if operators else "no_coverage",
            "is_estimate": False,
            "lang": _app_module.get_active_lang(),
            "operators": [_serialize_operator(op) for op in operators],
            "data_date": _app_module.get_data_date(_app_module.stations_db_path),
        })

    if not query:
        if wants_json:
            return jsonify({"status": "empty", "query": "", "operators": []})
        return render_template("best_operator.html", query="", state="empty",
                               operators=[])

    if len(query) > _MAX_QUERY_LEN or _too_few_letters(query):
        if wants_json:
            return jsonify({"status": "invalid", "query": query, "operators": []}), 400
        return render_template("best_operator.html", query=query, state="invalid",
                               operators=[]), 400

    app_module = _app_module

    try:
        outcome = app_module._resolve_address_coverage(query)
    except Exception:
        logger.exception("best_operator_page resolve failed")
        if wants_json:
            return jsonify({"status": "error", "query": query, "operators": []}), 500
        return render_template("best_operator.html", query=query, state="error",
                               operators=[]), 500

    status = outcome["status"]
    match = outcome.get("match")
    data_date = app_module.get_data_date(app_module.stations_db_path)

    if status == "no_match":
        if wants_json:
            return jsonify({"status": "no_match", "query": query, "operators": []}), 404
        return render_template("best_operator.html", query=query, state="no_match",
                               operators=[]), 404

    if status == "outside_pl":
        if wants_json:
            return jsonify({"status": "outside_pl", "query": query,
                            "match": match, "operators": []})
        return render_template("best_operator.html", query=query, state="outside_pl",
                               match=match, operators=[])

    coverage = outcome.get("coverage") or {}
    operators = rank_operators(coverage)
    _attach_referral_paths(operators)
    state = "ok" if operators else "no_coverage"
    is_estimate = outcome.get("is_estimate")

    if wants_json:
        return jsonify({
            "status": "ok" if operators else "no_coverage",
            "query": query,
            "match": match,
            "is_estimate": is_estimate,
            "lang": app_module.get_active_lang(),
            "operators": [_serialize_operator(op) for op in operators],
            "data_date": data_date,
        })

    disclaimer = app_module._COVERAGE_DISCLAIMER
    lang = app_module.get_active_lang()
    return render_template(
        "best_operator.html",
        query=query,
        state=state,
        match=match,
        is_estimate=is_estimate,
        operators=operators,
        data_date=data_date,
        disclaimer_text=disclaimer.get(lang) or disclaimer.get("en"),
    )


def go_operator(slug):
    slug = (slug or "").strip().lower()
    url = build_referral_url(slug)
    if not url:
        abort(404)
    try:
        referral_clicks_total.labels(operator=slug).inc()
    except Exception:
        logger.exception("referral_clicks_total inc failed for slug=%s", slug)
    return redirect(url, code=302)


def register_best_operator_routes(app, *, limiter=None):
    """Wire the blueprint onto the app. limiter is optional so the routes
    can also be registered onto a bare app in tests."""
    global _app_module
    _app_module = sys.modules.get(app.import_name)
    if limiter is not None:
        page_view = limiter.limit("30 per minute")(best_operator_page)
        go_view = limiter.limit("60 per minute")(go_operator)
    else:
        page_view, go_view = best_operator_page, go_operator

    best_operator_bp.add_url_rule("/best-operator", endpoint="best_operator_page",
                                  view_func=page_view, methods=["GET"])
    best_operator_bp.add_url_rule("/go/operator/<slug>", endpoint="go_operator",
                                  view_func=go_view, methods=["GET"])
    app.register_blueprint(best_operator_bp)
