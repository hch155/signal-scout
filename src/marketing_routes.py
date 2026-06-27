"""Marketing surface routes that compose existing public endpoints.

`register_marketing_routes(app)` wires the B2B demo page. It is gated behind
the same MARKETING_ENABLED feature flag as /pricing, /use-cases and /contact
so the whole marketing surface ships (or hides) as one unit — a CTA must
never link to a 404.

No new data logic lives here: /demo is a thin shell that calls the existing
/coverage_by_address and /coverage_card endpoints from the browser under the
anonymous tier (same-origin Referer satisfies require_api_access).
"""

from __future__ import annotations

from flask import jsonify, make_response, render_template

from config import settings


def register_marketing_routes(app):
    @app.route('/demo')
    def demo_page():
        if not settings.marketing_enabled:
            return jsonify({"error": "not_found"}), 404
        return make_response(render_template('demo.html'))
