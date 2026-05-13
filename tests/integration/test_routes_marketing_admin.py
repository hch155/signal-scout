"""Coverage-lifting tests for routes that didn't have any:
- Marketing pages behind MARKETING_ENABLED feature flag.
- Privacy / data-deletion legal pages.
- Email unsubscribe (token-signed).
- /admin/run_retention, /admin/run_coverage_alerts, /admin/stats auth shape.
- /coverage_gaps end-to-end against the test fixture.

These are deliberately shallow — they exercise the route, the auth gates,
and the happy-path JSON / HTML, not deep business logic. Their job is to
keep the coverage gate honest as the codebase grows.
"""
import dataclasses

import pytest

pytestmark = pytest.mark.integration


# ── Marketing pages (gated by settings.marketing_enabled) ───────────────────
#
# Why the patching dance: tests/unit/test_kms.py uses importlib.reload(config),
# which produces a *new* `settings` singleton. `app.py` did `from config
# import settings` at module-load time, so it still holds the OLD reference.
# Mutating only `config.settings` doesn't reach the route. Instead we monkey-
# patch app's *bound* reference to a fresh dataclass with the flag flipped.


def _patch_marketing(monkeypatch, enabled: bool):
    import app as app_mod
    import config as config_mod
    new_settings = dataclasses.replace(app_mod.settings, marketing_enabled=enabled)
    monkeypatch.setattr(app_mod, "settings", new_settings)
    monkeypatch.setattr(config_mod, "settings", new_settings)


@pytest.fixture
def marketing_off(monkeypatch):
    _patch_marketing(monkeypatch, False)
    yield


@pytest.fixture
def marketing_on(monkeypatch):
    _patch_marketing(monkeypatch, True)
    yield


def test_pricing_returns_404_when_marketing_off(client, marketing_off):
    r = client.get("/pricing")
    assert r.status_code == 404


def test_use_cases_returns_404_when_marketing_off(client, marketing_off):
    r = client.get("/use-cases")
    assert r.status_code == 404


def test_contact_returns_404_when_marketing_off(client, marketing_off):
    r = client.get("/contact")
    assert r.status_code == 404


def test_pricing_renders_when_marketing_on(client, marketing_on):
    r = client.get("/pricing")
    assert r.status_code == 200
    assert b"Signal-Scout" in r.data


def test_use_cases_renders_when_marketing_on(client, marketing_on):
    r = client.get("/use-cases")
    assert r.status_code == 200


def test_contact_renders_when_marketing_on(client, marketing_on):
    r = client.get("/contact")
    assert r.status_code == 200


def test_contact_with_known_plan_renders(client, marketing_on):
    for plan in ("starter", "pro", "enterprise"):
        r = client.get(f"/contact?plan={plan}")
        assert r.status_code == 200, f"plan={plan} should render"


def test_contact_with_unknown_plan_strips_silently(client, marketing_on):
    r = client.get("/contact?plan=evil-injection-attempt")
    assert r.status_code == 200  # Invalid plan gets normalised to '', no error.


# ── Legal / GDPR pages (no gate) ─────────────────────────────────────────────


def test_privacy_renders(client):
    r = client.get("/privacy")
    assert r.status_code == 200
    assert r.data  # markdown body present


def test_data_deletion_renders_inline_html(client):
    r = client.get("/data-deletion")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    # FB scrapes this; must contain the contact path so users can request deletion.
    assert "Signal-Scout" in body or "delete" in body.lower()


# ── /unsubscribe — token-signed pure GET path ────────────────────────────────


def test_unsubscribe_get_invalid_token_renders_page(client):
    # Bad token → page still renders (with `user=None`), no 500.
    r = client.get("/unsubscribe/not-a-real-token")
    assert r.status_code == 200


def test_unsubscribe_post_with_bad_token_returns_400(client):
    r = client.post("/unsubscribe/not-a-real-token")
    assert r.status_code == 400


# ── /admin/run_retention — auth shape ────────────────────────────────────────


def test_admin_run_retention_anon_returns_401(raw_client):
    r = raw_client.post("/admin/run_retention")
    assert r.status_code == 401


def _patch_bearer(monkeypatch, token: str):
    """Same dance as _patch_marketing — swap app's bound `settings` with
    a fresh dataclass holding the test bearer token."""
    import app as app_mod
    import config as config_mod
    new_settings = dataclasses.replace(app_mod.settings, metrics_bearer_token=token)
    monkeypatch.setattr(app_mod, "settings", new_settings)
    monkeypatch.setattr(config_mod, "settings", new_settings)


def test_admin_run_retention_with_bearer_token_succeeds(client, monkeypatch):
    """Cloud-Scheduler shape: bearer token bypasses session+CSRF."""
    _patch_bearer(monkeypatch, "test-bearer-x")
    r = client.post("/admin/run_retention",
                    headers={"Authorization": "Bearer test-bearer-x"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert "deleted" in body


def test_admin_run_retention_with_wrong_bearer_returns_401(raw_client, monkeypatch):
    _patch_bearer(monkeypatch, "real-token")
    r = raw_client.post("/admin/run_retention",
                        headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


# ── /admin/run_coverage_alerts ───────────────────────────────────────────────


def test_admin_run_coverage_alerts_anon_returns_401(raw_client):
    r = raw_client.post("/admin/run_coverage_alerts")
    assert r.status_code == 401


def test_admin_run_coverage_alerts_dry_run_with_bearer(client, monkeypatch):
    _patch_bearer(monkeypatch, "tok-y")
    r = client.post("/admin/run_coverage_alerts?dry-run=1",
                    headers={"Authorization": "Bearer tok-y"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert body["dry_run"] is True
    assert "counts" in body


def test_admin_run_coverage_alerts_unknown_user_returns_404(client, monkeypatch):
    _patch_bearer(monkeypatch, "tok-z")
    r = client.post(
        "/admin/run_coverage_alerts?user_email=nobody@nowhere.invalid",
        headers={"Authorization": "Bearer tok-z"},
    )
    assert r.status_code == 404
    body = r.get_json()
    assert body["error"] == "user_not_found"


# ── /admin/stats — auth shape ────────────────────────────────────────────────


def test_admin_stats_anon_returns_401(raw_client):
    r = raw_client.get("/admin/stats")
    assert r.status_code == 401


def test_admin_stats_non_admin_user_returns_403(authed_client):
    """Authed but non-admin user (random fresh email) → 403."""
    r = authed_client.get("/admin/stats")
    assert r.status_code == 403


def _promote_session_user_to_admin(client):
    """Flip the session user's role to 'admin' so subsequent requests
    pass the _is_admin gate without touching settings.admin_emails."""
    from models import User
    from database import db
    with client.session_transaction() as sess:
        uid = sess["user_id"]
    user = User.query.get(uid)
    user.role = "admin"
    db.session.commit()


def test_admin_stats_admin_user_returns_json_payload(authed_client):
    """?format=json on /admin/stats returns the aggregate dict."""
    _promote_session_user_to_admin(authed_client)
    r = authed_client.get("/admin/stats?days=7&format=json")
    assert r.status_code == 200
    body = r.get_json()
    for k in ("window_days", "total_events", "in_pl", "out_of_pl",
              "logged_in", "anonymous", "unique_sessions", "top_spots",
              "browsers", "daily_trend"):
        assert k in body, f"missing {k} in admin_stats payload"


def test_admin_stats_html_default_renders(authed_client):
    """No ?format=json → HTML template (admin_stats.html)."""
    _promote_session_user_to_admin(authed_client)
    r = authed_client.get("/admin/stats?days=7")
    assert r.status_code == 200
    assert r.data  # template body present


def test_admin_stats_caps_days_to_30(authed_client):
    _promote_session_user_to_admin(authed_client)
    r = authed_client.get("/admin/stats?days=999&format=json")
    assert r.status_code == 200
    assert r.get_json()["window_days"] == 30


def test_admin_stats_invalid_days_falls_back_to_default(authed_client):
    _promote_session_user_to_admin(authed_client)
    r = authed_client.get("/admin/stats?days=abc&format=json")
    assert r.status_code == 200
    assert r.get_json()["window_days"] == 1


# ── /admin/email_preview/<template> ──────────────────────────────────────────


def test_email_preview_anon_returns_401(raw_client):
    r = raw_client.get("/admin/email_preview/welcome")
    assert r.status_code == 401


def test_email_preview_non_admin_user_returns_403(authed_client):
    r = authed_client.get("/admin/email_preview/welcome")
    assert r.status_code == 403


def test_email_preview_unknown_template_returns_404(authed_client):
    _promote_session_user_to_admin(authed_client)
    r = authed_client.get("/admin/email_preview/not-a-real-template")
    assert r.status_code == 404
    body = r.get_json()
    assert "templates" in body  # surfaces the whitelist


@pytest.mark.parametrize("template", [
    "welcome", "password_changed", "2fa_enabled", "2fa_disabled",
    "recovery_used", "coverage_alert",
])
def test_email_preview_html_renders_for_each_template(authed_client, template):
    _promote_session_user_to_admin(authed_client)
    r = authed_client.get(f"/admin/email_preview/{template}")
    assert r.status_code == 200, f"{template} preview failed"
    assert r.data  # HTML body present


def test_email_preview_txt_format_returns_text_plain(authed_client):
    _promote_session_user_to_admin(authed_client)
    r = authed_client.get("/admin/email_preview/welcome?fmt=txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["Content-Type"]


def test_email_preview_invalid_fmt_falls_back_to_html(authed_client):
    _promote_session_user_to_admin(authed_client)
    r = authed_client.get("/admin/email_preview/welcome?fmt=jpeg")
    assert r.status_code == 200
    # Default html → no text/plain content-type set explicitly.
    assert "text/plain" not in r.headers.get("Content-Type", "")


# ── /coverage_gaps via fixture ───────────────────────────────────────────────


def test_coverage_gaps_returns_summary(client):
    """End-to-end against the test fixture stations DB. Returns the
    {gaps, summary} payload — exercises queries.find_coverage_gaps."""
    r = client.get("/coverage_gaps?lat=52.2297&lng=21.0122")
    assert r.status_code == 200
    body = r.get_json()
    assert "gaps" in body
    assert "summary" in body
    assert {"total_bands", "covered", "dead"}.issubset(body["summary"].keys())


def test_coverage_gaps_invalid_lat_lng_returns_400(client):
    """Non-numeric lat/lng → 400 (parse error)."""
    r = client.get("/coverage_gaps?lat=abc&lng=def")
    assert r.status_code == 400


def test_coverage_gaps_out_of_bounds_returns_200_with_flag(client):
    """Out-of-bounds coords → 200 with outside_pl=True (frontend
    handles the empty case uniformly with /stations)."""
    r = client.get("/coverage_gaps?lat=10&lng=10")
    assert r.status_code == 200
    body = r.get_json()
    assert body["outside_pl"] is True
    assert body["gaps"] == []


# ── /unsubscribe — full happy path with a real token ─────────────────────────


def test_unsubscribe_full_flow_disables_alerts(authed_client):
    """Generate a real signed token via the same serializer the email
    sender uses, hit the GET + POST, confirm the User row flips."""
    from itsdangerous import URLSafeSerializer
    from config import settings
    from models import User
    from database import db

    user = User.query.filter_by(email_alerts_enabled=True).first()
    assert user is not None, "authed_client fixture should give us one user"

    serializer = URLSafeSerializer(settings.secret_key, salt="email-unsubscribe")
    token = serializer.dumps(user.id)

    # GET — preview page with the user's email visible.
    r = authed_client.get(f"/unsubscribe/{token}")
    assert r.status_code == 200

    # POST — actually flips the bit.
    r = authed_client.post(f"/unsubscribe/{token}")
    assert r.status_code == 200

    db.session.refresh(user)
    assert user.email_alerts_enabled is False
