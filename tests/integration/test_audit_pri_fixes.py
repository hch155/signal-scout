"""Regression coverage for re-audit batch PR I:
- L-NEW-4: honeypot rows planted in BaseStation table so prefix
  scrapers surface them (closes the bypass where /search_stations
  + /find_station chain never queried env-list-only honeypots).
"""
from __future__ import annotations



def test_seed_honeypot_rows_inserts_when_env_set(app, monkeypatch):
    from database import db
    from models import BaseStation
    from api_access import seed_honeypot_rows, HONEYPOT_PROVIDER_MARKER

    # Seed two known IDs.
    monkeypatch.setenv("HONEYPOT_BTS_IDS", "PRI_HP_A,PRI_HP_B")
    # _load_honeypot_ids reads env at call time, so no need to reset.
    inserted = seed_honeypot_rows(app, db)
    assert inserted == 2

    with app.app_context():
        rows = BaseStation.query.filter_by(
            service_provider=HONEYPOT_PROVIDER_MARKER
        ).all()
        ids = {r.basestation_id for r in rows}
        assert {"PRI_HP_A", "PRI_HP_B"}.issubset(ids)
        # Coordinates must land inside Polish bounds.
        for r in rows:
            if r.basestation_id in ("PRI_HP_A", "PRI_HP_B"):
                assert 49.0 <= r.latitude <= 55.5
                assert 14.0 <= r.longitude <= 24.2


def test_seed_honeypot_rows_idempotent(app, monkeypatch):
    """Running the seeder twice in a row inserts the rows once and
    is a no-op the second time."""
    from database import db
    from api_access import seed_honeypot_rows

    monkeypatch.setenv("HONEYPOT_BTS_IDS", "PRI_HP_C")
    first = seed_honeypot_rows(app, db)
    second = seed_honeypot_rows(app, db)
    assert first >= 1
    assert second == 0


def test_seed_honeypot_rows_noop_when_env_unset(app, monkeypatch):
    monkeypatch.delenv("HONEYPOT_BTS_IDS", raising=False)
    from database import db
    from api_access import seed_honeypot_rows
    assert seed_honeypot_rows(app, db) == 0


def test_search_stations_returns_honeypot_row_when_prefix_matches(
        client, app, monkeypatch):
    """The whole point of this PR: a scraper using /search_stations
    with a prefix that matches a honeypot ID must see the row in the
    response. The follow-up /find_station then triggers
    record_honeypot_hit via the existing env-list lookup.

    /search_stations validates the query as 2-7 alphanumerics, so we
    use a short alphanumeric honeypot ID for the test (matching the
    real-world shape of basestation_id anyway)."""
    from database import db
    from api_access import seed_honeypot_rows

    # 6-char alphanumeric, fits the q= 2-7 constraint.
    hp_id = "HPABC1"
    monkeypatch.setenv("HONEYPOT_BTS_IDS", hp_id)
    seed_honeypot_rows(app, db)

    r = client.get(
        f"/search_stations?q={hp_id[:3]}",  # prefix search
        headers={"Referer": "http://localhost/"},
    )
    assert r.status_code == 200
    body = r.get_json() or {}
    flat = str(body)
    assert hp_id in flat, (
        "honeypot row didn't surface in /search_stations — "
        "L-NEW-4 regressed (env-list-only honeypots are bypassable)"
    )
