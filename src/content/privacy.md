# Privacy Policy

_Last updated: 24 April 2026_

This privacy notice explains what personal data Signal-Scout collects, how it is used, and the rights you have over it. It is written to satisfy the GDPR's transparency obligations (Art. 13 / 14). It is **not** legal advice; if you intend to rely on Signal-Scout for sensitive operations or to integrate it into a regulated workflow, get your own counsel to review.

## Who we are

**Signal-Scout** is operated by Hubert Cylwik as an independent project. The dataset surfaced by this app comes from Urząd Komunikacji Elektronicznej (UKE), the Polish telecommunications regulator, and is publicly licensed.

- **Data controller:** Hubert Cylwik
- **Contact:** hcylwik@gmail.com
- **Service URL:** https://signal-scout.com

## What we collect

### When you visit the public site (no account)

- A **session cookie** (`session=...`) created by Flask. It carries no identifying information; it only links your browser back to a server-side session record so the map remembers your last clicked location during the visit. Strictly necessary for the app to function — no consent required (GDPR Recital 30 / ePrivacy Art. 5(3)).
- A **CSRF token** stored in the session, used to protect form submissions (e.g. registration, login).
- **Server access logs** retained by Cloud Run for service diagnostics. These contain your IP address (truncated to /24 for IPv4 / /48 for IPv6 in our application audit log), HTTP method, path, status code, response time. Retention: 30 days at the infrastructure level.

### When you create an account

- The **email address** you registered with.
- A **bcrypt hash of your password** (we never store the plaintext).
- The **company name** you optionally provided.
- An **API key** stored as a SHA-256 hash plus a non-secret prefix for display (we never store the plaintext token after creation).
- If you enable 2FA: an encrypted **TOTP secret** and bcrypt hashes of one-time recovery codes.
- An **audit log** of security-relevant actions on your account (logins, logouts, password changes, API key creation/revocation, 2FA changes) including the truncated IP and a coarse browser identifier. This is shown back to you on `/account` so you can spot suspicious activity.

### When you save a location for change alerts

- The **name, latitude, longitude, radius and alerting toggle** you provided.
- **Snapshots** of the BTS dataset within your saved radius (no personal data — just a list of public radio permits).
- The diff between snapshots, which we use to populate `/account/locations/<id>/changes`.

### When you use the map

- The **coordinates you click** are stored in your session for the duration of the visit so the sidebar can show "stations near your spot".
- We write a **pseudonymised event** for each click — timestamp, coordinates rounded to ~1 km grid, a one-way `sha256(session_id)` pseudonym, browser class (`browser_chrome` / `mobile` / etc., not the full UA string), API tier. We never record your raw IP or the precise coordinates. Used in aggregate to understand which areas of Poland the app is being used in (top spots, browser breakdown, in-PL vs out-of-PL). Retention: **30 days, deleted automatically on every server boot**. Legal basis: legitimate interest (Art. 6(1)(f)).

### What we don't collect

- We do **not** use third-party advertising trackers (Google Ads / Meta Pixel / similar).
- We do **not** sell or share your data with third parties for marketing.
- We do **not** combine our logs with external profiles to build a marketing identity.

## Why we collect it (legal bases)

| Data | Purpose | Legal basis |
|------|---------|-------------|
| Session + CSRF cookie | Make the app work | Strictly necessary (Art. 6(1)(b) — performance of a contract) |
| Email + password | Account authentication | Performance of a contract (Art. 6(1)(b)) |
| API key hash | Authenticate API requests | Performance of a contract (Art. 6(1)(b)) |
| Saved locations / snapshots | Deliver the alert feature you asked for | Performance of a contract (Art. 6(1)(b)) |
| Audit log | Detect and investigate security incidents | Legitimate interest (Art. 6(1)(f)) — service security |
| Truncated IPs | Rate limiting + abuse prevention | Legitimate interest (Art. 6(1)(f)) |
| Aggregated usage events (future) | Understand product usage to improve the service | Legitimate interest (Art. 6(1)(f)) |

## How long we keep it

| Data | Retention |
|------|-----------|
| Account (email, password, 2FA, locations, snapshots) | Until you delete your account |
| Audit log | Lifetime of the account, then cascaded on deletion |
| Server access logs (Cloud Run infra) | 30 days |
| Aggregated usage events (when shipped) | 30 days |
| Session cookie | Browser session / until logout |

## Where it is stored

- **Application data** (your account, saved locations, snapshots, audit log) — Google Cloud Run + a SQLite database backed by Google Cloud Storage, region `europe-central2` (Warsaw, Poland). Data does not leave the EU.
- **Server logs** — Google Cloud Logging, region `europe-central2`.

## Sub-processors

| Provider | Purpose | Region |
|----------|---------|--------|
| Google Cloud Platform (Cloud Run, Cloud Storage, Cloud Logging) | Application hosting + data storage | `europe-central2` (Warsaw, Poland) |
| Squarespace, Inc. | Domain registrar + apex 302 redirect | United States (transfer governed by Squarespace's GDPR DPA) |

We do not use any third-party analytics, advertising, or tracking processors.

## Your rights

Under the GDPR you have the right to:

- **Access** the personal data we hold about you. For account-derived data this is visible directly on `/account`. For anything else, email us.
- **Rectify** inaccurate data — change your email or company name on `/account`.
- **Erase** your data ("right to be forgotten") — `/account` has a "Delete account" action that immediately wipes your account, audit log, saved locations, snapshots, and API keys (cascade delete). Truncated IPs in old logs persist for the access-log retention window.
- **Restrict** processing or **object** to it on legitimate-interest grounds — email us.
- **Portability** — export of saved locations / snapshots is available on request.
- **Lodge a complaint** with the Polish supervisory authority (Urząd Ochrony Danych Osobowych, https://uodo.gov.pl).

To exercise any of these rights, email **hcylwik@gmail.com** with the email address you registered with. We aim to respond within 30 days.

## Children

Signal-Scout is not directed at children under 16 and we do not knowingly collect their data. If you believe a child has registered, email us and we will delete the account.

## Changes to this notice

We will update this page when we change what we collect or how we use it. Material changes will be flagged in the footer with the "Last updated" date above. The current version always lives at `/privacy`.

## Contact

- Email: **hcylwik@gmail.com**
- Source code: [github.com/hch155/signal-scout](https://github.com/hch155/signal-scout) — what we say here matches what the code does.
