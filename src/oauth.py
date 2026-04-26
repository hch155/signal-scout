"""OAuth sign-in (Google + GitHub) — PR #48.7.

Wrapped around Authlib's Flask client. Adds two providers, both
optional — if their client_id/secret env vars are empty, the
provider's `/auth/<name>/login` route 404s and the /login UI hides
the button. So flipping a provider on/off is a Cloud Run env update
plus redeploy, no code change.

Sign-in flow:
1. User clicks "Sign in with Google" on /login → /auth/google/login
2. We redirect to Google with our client_id + a CSRF state we own
3. Google bounces them back to /auth/google/callback?code=...&state=...
4. We exchange the code for an ID token, verify state, pull the email
5. Upsert User by email — first time creates a new account, returning
   user just gets a session.

Same shape for GitHub. GitHub's /user endpoint returns a `email` field
only if the user marked one as public; for private-email users we hit
/user/emails (extra scope `user:email`) to find the primary verified
address.

OAuth-created accounts:
- Have a random, unusable password_hash (you can't log in with the
  password — no UI lets you, and the bcrypt comparison would fail).
- Have email_verified_at stamped immediately (the provider already
  verified the address — no need for our verify-email round-trip).
- Use the same User row as password-auth users; if a password user
  later signs in via Google with the same email, they get logged in
  as the same account (we treat email as the identity).

Security notes:
- `state` parameter prevents CSRF (Authlib generates + verifies it)
- `nonce` parameter on Google prevents token replay (Authlib handles)
- We pin scopes to `openid email profile` (Google) / `read:user
  user:email` (GitHub) — the minimum to get an email address.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Optional

from flask import Flask, redirect, request, session, url_for, jsonify
from authlib.integrations.flask_client import OAuth

from config import settings


logger = logging.getLogger(__name__)
oauth = OAuth()


def init_oauth(app: Flask) -> None:
    """Register Google + GitHub providers on the global oauth instance.

    Skips registration when credentials are missing — `oauth.create_client('google')`
    will return None for the missing one, and the route handlers below
    short-circuit to a 404."""
    oauth.init_app(app)
    if settings.google_oauth_client_id and settings.google_oauth_client_secret:
        oauth.register(
            name='google',
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile'},
        )
    if settings.github_oauth_client_id and settings.github_oauth_client_secret:
        oauth.register(
            name='github',
            client_id=settings.github_oauth_client_id,
            client_secret=settings.github_oauth_client_secret,
            access_token_url='https://github.com/login/oauth/access_token',
            authorize_url='https://github.com/login/oauth/authorize',
            api_base_url='https://api.github.com/',
            client_kwargs={'scope': 'read:user user:email'},
        )
    if settings.facebook_oauth_client_id and settings.facebook_oauth_client_secret:
        # Facebook Graph API v18.0. `email` scope is granted without App
        # Review for individual apps; verified email comes back via
        # /me?fields=email,name. Note: the FB app must be in Live Mode (not
        # Development Mode) for non-admin users to authenticate.
        oauth.register(
            name='facebook',
            client_id=settings.facebook_oauth_client_id,
            client_secret=settings.facebook_oauth_client_secret,
            access_token_url='https://graph.facebook.com/v18.0/oauth/access_token',
            authorize_url='https://www.facebook.com/v18.0/dialog/oauth',
            api_base_url='https://graph.facebook.com/v18.0/',
            client_kwargs={'scope': 'email'},
        )


def _provider_enabled(name: str) -> bool:
    if name == 'google':
        return bool(settings.google_oauth_client_id)
    if name == 'github':
        return bool(settings.github_oauth_client_id)
    if name == 'facebook':
        return bool(settings.facebook_oauth_client_id)
    return False


def login_with_provider(provider: str):
    """Kicks off the OAuth flow. Redirects to the provider's
    authorization endpoint with a state parameter that Authlib stores
    in the session for later verification."""
    if not _provider_enabled(provider):
        return jsonify({'error': 'provider_not_configured'}), 404
    client = oauth.create_client(provider)
    if client is None:
        return jsonify({'error': 'provider_not_configured'}), 404
    redirect_uri = url_for(f'oauth_{provider}_callback', _external=True)
    return client.authorize_redirect(redirect_uri)


def callback_for_provider(provider: str):
    """Handles the redirect back from the provider. Pulls the email,
    upserts a User row, sets the session. Always returns a 302 — to
    /account on success, /login on any failure."""
    if not _provider_enabled(provider):
        return redirect(url_for('home') + '?oauth_error=provider_not_configured')
    client = oauth.create_client(provider)
    if client is None:
        return redirect(url_for('home') + '?oauth_error=provider_not_configured')
    try:
        token = client.authorize_access_token()
    except Exception:
        logger.exception("OAuth token exchange failed for %s", provider)
        return redirect(url_for('home') + '?oauth_error=token_exchange')

    email = _resolve_email(provider, client, token)
    if not email:
        return redirect(url_for('home') + '?oauth_error=no_email')

    from models import User
    from database import db
    user = User.query.filter(db.func.lower(User.email) == email.lower()).first()
    if user is None:
        # First time we see this email — create an OAuth-only user. The
        # `!OAUTH-` prefix is a sentinel: there's no real password, so
        # bcrypt comparison can never succeed (refusing password login
        # for the same email later would otherwise be a back door).
        user = User(
            email=email,
            password_hash='!OAUTH-' + secrets.token_urlsafe(32),
            api_tier='free',
            email_alerts_enabled=True,
            registration_date=datetime.utcnow(),
        )
        db.session.add(user)
    else:
        # ── Account-takeover protection (audit Critical 2) ──
        # The user already exists. If their password_hash is a real
        # bcrypt hash (NOT the `!OAUTH-` sentinel), they registered
        # with a password. Accepting the OAuth login here would let
        # anyone who controls a provider account with the victim's
        # email take over the password account — Facebook in
        # particular doesn't expose `email_verified` so we can't
        # trust the provider to have done the verification for us.
        # Refuse the login; the legitimate owner can sign in with
        # their password and link a provider from /account explicitly.
        ph = user.password_hash or ''
        if ph and not ph.startswith('!OAUTH-'):
            logger.warning(
                "OAuth login refused: password account exists "
                "for email=%s provider=%s", email, provider,
            )
            return redirect(
                url_for('home') +
                '?oauth_error=password_account_exists'
            )

    user.last_login_date = datetime.utcnow()
    user.failed_login_attempts = 0
    user.locked_until = None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        # Audit fix (Medium privacy — log redaction): drop the email
        # from the log line. user_id is enough for triage and avoids
        # PII in centralized logging / Cloud Logging exports.
        logger.exception("OAuth upsert commit failed for user_id=%s provider=%s",
                         getattr(user, 'id', None), provider)
        return redirect(url_for('home') + '?oauth_error=db')

    # ── 2FA gate (audit Critical 1) ──
    # If the user enabled TOTP, password sign-in routes them to a
    # half-session (`pending_2fa_user_id`) before granting a real
    # session. OAuth must do the same — anything less is a 2FA bypass.
    # We park them in the same half-session and redirect to a tiny
    # form that consumes /login/totp.
    preserved_csrf = session.get('_csrf_token') or secrets.token_hex(32)
    if getattr(user, 'totp_enabled', False):
        session.clear()
        session['_csrf_token'] = preserved_csrf
        session['pending_2fa_user_id'] = user.id
        return redirect('/auth/2fa_challenge')

    # Promote to a full session.
    session.clear()
    session['_csrf_token'] = preserved_csrf
    session['user_id'] = user.id

    return redirect('/account')


def _resolve_email(provider: str, client, token) -> Optional[str]:
    """Fish out the verified primary email from the provider."""
    if provider == 'google':
        # `id_token` carries the email + email_verified claims (OIDC).
        info = token.get('userinfo')
        if info and info.get('email'):
            if info.get('email_verified'):
                return info['email']
        # Fallback: hit the userinfo endpoint with the access_token.
        try:
            resp = client.get('https://openidconnect.googleapis.com/v1/userinfo',
                              token=token)
            payload = resp.json()
            if payload.get('email_verified'):
                return payload.get('email')
        except Exception:
            logger.exception("google userinfo fetch failed")
        return None

    if provider == 'github':
        # Audit fix (Critical 2 — Account Takeover):
        # Skip /user.email — that field can be a public profile email
        # the user typed in, not necessarily verified by GitHub. Use
        # /user/emails exclusively, which exposes the per-address
        # verified flag, and only return addresses where verified=true.
        # Requires the `user:email` scope (already requested in init).
        try:
            resp = client.get('user/emails', token=token)
            emails = resp.json() or []
            for e in emails:
                if e.get('primary') and e.get('verified'):
                    return e.get('email')
            for e in emails:  # any verified address as a last resort
                if e.get('verified'):
                    return e.get('email')
        except Exception:
            logger.exception("github /user/emails fetch failed")
        return None

    if provider == 'facebook':
        # Graph API /me with email field. FB users without an email on
        # file (rare but possible — phone-only signups) get None back.
        try:
            resp = client.get('me?fields=email,name', token=token)
            payload = resp.json() or {}
            return payload.get('email')
        except Exception:
            logger.exception("facebook /me fetch failed")
        return None

    return None
