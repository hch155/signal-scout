"""Ops probes: readiness (/readyz DB check) + request-id propagation."""


def test_readyz_verifies_both_db_binds(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ready"
    assert body["checks"] == {"stations_db": "ok", "users_db": "ok"}


def test_healthz_stays_shallow_liveness(client):
    # /healthz must remain a cheap liveness probe (no DB), distinct from /readyz.
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json().get("status") == "ok"


def test_responses_carry_request_id(client):
    r = client.get("/healthz")
    assert r.headers.get("X-Request-ID")


def test_request_id_is_honored_from_caller(client):
    r = client.get("/healthz", headers={"X-Request-ID": "trace-abc-123"})
    assert r.headers.get("X-Request-ID") == "trace-abc-123"


def test_request_id_rejects_malformed(client):
    # A junk/oversized incoming id is replaced with a fresh generated one.
    r = client.get("/healthz", headers={"X-Request-ID": "bad id with spaces!!"})
    rid = r.headers.get("X-Request-ID")
    assert rid and rid != "bad id with spaces!!"
