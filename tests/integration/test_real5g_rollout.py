"""/rollout view + /api/v1/real5g_rollout JSON + the real_five_g_snapshot
read/write API. The routes are registered on the test app here (the prod
wiring lives in app.py via register_real5g_routes)."""
import pytest


@pytest.fixture(autouse=True)
def _rollout_routes(app):
    """Register the rollout routes once on the session app and start each
    test from an empty real_five_g_snapshot table.

    The session app may already have handled a request (Flask then blocks
    @app.route), so the setup-finished flag is briefly cleared — the prod
    wiring registers at boot, before any request."""
    from database import db
    from real5g_routes import register_real5g_routes
    from real5g_rollout import RealFiveGSnapshot

    if 'rollout_page' not in app.view_functions:
        prev = getattr(app, '_got_first_request', False)
        app._got_first_request = False
        try:
            register_real5g_routes(app)
        finally:
            app._got_first_request = prev
    with app.app_context():
        db.create_all()
        db.session.query(RealFiveGSnapshot).delete()
        db.session.commit()
    yield
    with app.app_context():
        db.session.query(RealFiveGSnapshot).delete()
        db.session.commit()


def test_rollout_page_renders(client):
    r = client.get('/rollout')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Real-5G Rollout' in body
    # The fixture has Orange + Play 3.5 GHz sites — both labels render.
    assert 'Orange' in body
    assert 'Play' in body
    assert 'mazowieckie' in body


def test_api_real5g_rollout_json(client):
    r = client.get('/api/v1/real5g_rollout')
    assert r.status_code == 200
    data = r.get_json()
    assert data['total_sites'] == 12
    assert data['by_operator'] == {
        'Orange Polska S.A.': 6,
        'P4 sp. z o.o.': 6,
    }
    assert data['by_voivodeship']['mazowieckie'] == 4
    assert sum(data['by_operator'].values()) == data['total_sites']
    assert sum(data['by_voivodeship'].values()) == data['total_sites']


def test_snapshot_write_read_previous_roundtrip(app):
    from real5g_rollout import (
        maybe_write_real5g_snapshot,
        previous_real5g_snapshot,
        read_real5g_history,
    )
    a = {'by_operator': {'Orange Polska S.A.': 10},
         'by_voivodeship': {'mazowieckie': 10}, 'total_sites': 10}
    b = {'by_operator': {'Orange Polska S.A.': 14},
         'by_voivodeship': {'mazowieckie': 14}, 'total_sites': 14}
    with app.app_context():
        assert maybe_write_real5g_snapshot(None, '2026-04-25', a) is True
        assert maybe_write_real5g_snapshot(None, '2026-05-25', b) is True
        # Duplicate key is a no-op.
        assert maybe_write_real5g_snapshot(None, '2026-05-25', b) is False

        rows = read_real5g_history(None)
        assert [r['snapshot_key'] for r in rows] == ['2026-04-25', '2026-05-25']
        assert rows[0]['total_sites'] == 10
        assert rows[1]['by_operator'] == {'Orange Polska S.A.': 14}

        prev = previous_real5g_snapshot(None, '2026-05-25')
        assert prev['snapshot_key'] == '2026-04-25'
        assert previous_real5g_snapshot(None, '2026-04-25') is None


def test_rollout_render_writes_snapshot_and_shows_delta(app, client):
    from real5g_rollout import maybe_write_real5g_snapshot, read_real5g_history
    # Seed an older snapshot so the current render has a baseline to diff.
    with app.app_context():
        maybe_write_real5g_snapshot(
            None, '2000-01-01',
            {'by_operator': {'Orange Polska S.A.': 1, 'P4 sp. z o.o.': 1},
             'by_voivodeship': {'mazowieckie': 2}, 'total_sites': 2},
        )

    r = client.get('/rollout')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # Current (6/6) > seeded (1/1) → an "up" delta badge renders.
    assert '▲' in body

    # The render also recorded a snapshot for the fixture's data date.
    with app.app_context():
        keys = [row['snapshot_key'] for row in read_real5g_history(None)]
    assert '2000-01-01' in keys
    assert len(keys) >= 2
