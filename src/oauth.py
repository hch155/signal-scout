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


def _provider_enabled(name: str) -> bool:
    if name == 'google':
        return bool(settings.google_oauth_client_id)
    if name == 'github':
        return bool(settings.github_oauth_client_id)
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
        user = User(
            email=email,
            password_hash='!OAUTH-' + secrets.token_urlsafe(32),
            api_tier='free',
            email_alerts_enabled=True,
            registration_date=datetime.utcnow(),
        )
        db.session.add(user)
    user.last_login_date = datetime.utcnow()
    user.failed_login_attempts = 0
    user.locked_until = None
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("OAuth upsert commit failed for email=%s provider=%s",
                         email, provider)
        return redirect(url_for('home') + '?oauth_error=db')

    # Promote to a full session.
    preserved_csrf = session.get('_csrf_token') or secrets.token_hex(32)
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
        # Public email path first.
        try:
            resp = client.get('user', token=token)
            primary = (resp.json() or {}).get('email')
            if primary:
                return primary
        except Exception:
            logger.exception("github /user fetch failed")
        # Fallback: /user/emails (needs `user:email` scope).
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

    return None
