import pytest

pytestmark = pytest.mark.integration

GET_URL = "/api/v1/coverage_by_address"
BATCH_URL = "/api/v1/coverage_by_address/batch"

@pytest.fixture
def api_key(app):
    """A minted free-tier API key header — the batch endpoint now requires one."""
    from database import db
    from models import User, ApiKey
    from api_access import hash_api_key
    raw = "batch-test-key-abc123"
    with app.app_context():
        u = User(email="batch-tester@example.com", password_hash="x",
                 api_key_hash=hash_api_key(raw), api_tier="free")
        db.session.add(u); db.session.commit()
        uid = u.id
    yield {"X-API-Key": raw}
    with app.app_context():
        ApiKey.query.filter_by(user_id=uid).delete(synchronize_session=False)
        u = db.session.get(User, uid)
        if u:
            db.session.delete(u); db.session.commit()



def test_known_address_returns_full_coverage_payload(client):
    r = client.get(GET_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    body = r.get_json()

    assert body["query"] == "Marszałkowska Warszawa"

    match = body["match"]
    assert match["display"] == "Marszałkowska, Warszawa"
    assert match["latitude"] == pytest.approx(52.2297, abs=1e-3)
    assert match["longitude"] == pytest.approx(21.0122, abs=1e-3)
    assert match["geocode_precision"] == "street_centroid"
    assert match["confidence"] == "medium"

    coverage = body["coverage"]
    assert set(coverage) == {"signal_tier", "signal_score", "real_5g", "operators"}
    assert coverage["signal_tier"] == "Excellent"
    assert isinstance(coverage["operators"], list) and coverage["operators"]

    labels = body["labels"]
    assert labels["tier_pl"] == "Bardzo dobry"
    assert labels["real_5g_pl"] == "Prawdziwe 5G (3,5 GHz)"
    assert "headline_pl" in labels

    assert body["is_estimate"] is True
    assert body["disclaimer"]["pl"] and body["disclaimer"]["en"]
    assert body["data_date"]


def test_known_address_has_no_raw_stations(client):
    r = client.get(GET_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    body = r.get_json()
    assert "stations" not in body
    assert "stations" not in body["coverage"]
    for op in body["coverage"]["operators"]:
        assert "stations" not in op
        assert "location" not in op
        assert "latitude" not in op


def test_real_5g_true_when_c_band_in_range(client):
    r = client.get(GET_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    coverage = r.get_json()["coverage"]
    assert coverage["real_5g"] is True
    real_ops = [o for o in coverage["operators"] if o["real_5g"]]
    assert real_ops
    assert any(mhz >= 3400 for o in real_ops for mhz in o["5g_bands_mhz"])


def test_real_5g_false_when_no_c_band_in_range(client):
    r = client.get(GET_URL, query_string={"q": "Łąkowa Białystok"})
    assert r.status_code == 200
    body = r.get_json()
    coverage = body["coverage"]
    assert coverage["real_5g"] is False
    assert coverage["signal_tier"] is None
    assert coverage["operators"] == []
    assert body["labels"]["real_5g_pl"] == "Brak 5G"


def test_no_match_returns_404(client):
    r = client.get(GET_URL, query_string={"q": "Qwerty Asdfgh"})
    assert r.status_code == 404
    assert r.get_json()["error"] == "no_match"


def test_conflicting_freeform_and_structured_returns_400(client):
    r = client.get(GET_URL, query_string={"q": "Marszałkowska Warszawa", "city": "Warszawa"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "conflicting_input"


def test_outside_pl_returns_200_with_null_coverage(client, monkeypatch):
    monkeypatch.setattr(
        "app.search_addresses",
        lambda *a, **k: [{"display": "Somewhere, Sweden", "lat": 60.0, "lng": 18.0}],
    )
    r = client.get(GET_URL, query_string={"q": "Somewhere Sweden"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["outside_pl"] is True
    assert body["coverage"] is None
    assert body["match"]["display"] == "Somewhere, Sweden"


def test_batch_mixes_per_item_status_and_echoes_id(client, api_key):
    payload = {"addresses": [
        {"id": "good", "q": "Marszałkowska Warszawa"},
        {"id": "bad", "q": "Qwerty Asdfgh"},
    ]}
    r = client.post(BATCH_URL, headers=api_key, json=payload)
    assert r.status_code == 200
    body = r.get_json()
    assert body["count"] == 2
    by_id = {row["id"]: row for row in body["results"]}

    assert by_id["good"]["status"] == "ok"
    assert by_id["good"]["coverage"]["signal_tier"] == "Excellent"
    assert by_id["good"]["labels"]["tier_pl"] == "Bardzo dobry"
    assert by_id["good"]["is_estimate"] is True
    assert by_id["good"]["disclaimer"]["pl"]

    assert by_id["bad"]["status"] == "no_match"
    assert "coverage" not in by_id["bad"]


def test_known_address_emits_english_labels(client):
    r = client.get(GET_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    labels = r.get_json()["labels"]
    assert labels["tier_en"] == "Excellent"
    assert labels["real_5g_en"] == "Real 5G (3.5 GHz)"
    assert "headline_en" in labels


def test_operator_technologies_are_booleans(client):
    r = client.get(GET_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    operators = r.get_json()["coverage"]["operators"]
    assert operators
    for op in operators:
        assert op["technologies"]
        assert all(isinstance(v, bool) for v in op["technologies"].values())


def test_known_address_is_edge_cacheable(client):
    r = client.get(GET_URL, query_string={"q": "Marszałkowska Warszawa"})
    assert r.status_code == 200
    cc = r.headers.get("Cache-Control", "")
    assert "public" in cc and "max-age=" in cc


def test_overlong_query_returns_400(client):
    r = client.get(GET_URL, query_string={"q": "a" * 121})
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid_input"


def test_batch_coerces_and_caps_id(client, api_key):
    r = client.post(BATCH_URL, headers=api_key, json={"addresses": [
        {"id": 12345, "q": "Qwerty Asdfgh"},
        {"id": "x" * 300, "q": "Qwerty Asdfgh"},
    ]})
    assert r.status_code == 200
    rows = r.get_json()["results"]
    assert rows[0]["id"] == "12345"
    assert len(rows[1]["id"]) == 128


def test_batch_internal_error_maps_to_error_status(client, monkeypatch, api_key):
    import app as app_module

    def _boom(_query):
        raise RuntimeError("resolver down")

    monkeypatch.setattr(app_module, "_resolve_address_coverage", _boom)
    r = client.post(BATCH_URL, headers=api_key, json={"addresses": [{"id": "x", "q": "Marszałkowska Warszawa"}]})
    assert r.status_code == 200
    row = r.get_json()["results"][0]
    assert row["id"] == "x"
    assert row["status"] == "error"
    assert "coverage" not in row


def test_too_few_letters_returns_400(client):
    for q in ("123", "ab"):
        r = client.get(GET_URL, query_string={"q": q})
        assert r.status_code == 400, q
        assert r.get_json()["error"] == "invalid_input"


def test_batch_ambiguous_status_for_conflicting_and_too_short(client, api_key):
    r = client.post(BATCH_URL, headers=api_key, json={"addresses": [
        {"id": "conflict", "q": "Marszałkowska Warszawa", "city": "Warszawa"},
        {"id": "short", "q": "12"},
    ]})
    assert r.status_code == 200
    by_id = {row["id"]: row for row in r.get_json()["results"]}
    assert by_id["conflict"]["status"] == "ambiguous"
    assert by_id["short"]["status"] == "ambiguous"
    assert "coverage" not in by_id["conflict"]
    assert "coverage" not in by_id["short"]


def test_batch_good_outside_pl_and_no_match(client, monkeypatch, api_key):
    import app as app_module
    real_search = app_module.search_addresses

    def fake_search(query, db_path, *args, **kwargs):
        if "sweden" in query.lower():
            return [{"display": "Somewhere, Sweden", "lat": 60.0, "lng": 18.0}]
        return real_search(query, db_path, *args, **kwargs)

    monkeypatch.setattr(app_module, "search_addresses", fake_search)
    r = client.post(BATCH_URL, headers=api_key, json={"addresses": [
        {"id": "good", "q": "Marszałkowska Warszawa"},
        {"id": "out", "q": "Somewhere Sweden"},
        {"id": "bad", "q": "Qwerty Asdfgh"},
    ]})
    assert r.status_code == 200
    by_id = {row["id"]: row for row in r.get_json()["results"]}

    assert by_id["good"]["status"] == "ok"
    assert by_id["good"]["coverage"]["operators"]

    assert by_id["out"]["status"] == "outside_pl"
    assert by_id["out"]["match"]["display"] == "Somewhere, Sweden"
    assert "coverage" not in by_id["out"]

    assert by_id["bad"]["status"] == "no_match"
    assert "coverage" not in by_id["bad"]


def test_batch_envelope_includes_data_date(client, api_key):
    r = client.post(BATCH_URL, headers=api_key, json={"addresses": [{"id": "a", "q": "Marszałkowska Warszawa"}]})
    assert r.status_code == 200
    assert r.get_json()["data_date"]


def test_cacheable_routes_set_no_cookie(client):
    for url in ("/api/v1/coverage_by_address", "/coverage_by_address"):
        r = client.get(url, query_string={"q": "Marszałkowska Warszawa"})
        assert r.status_code == 200, url
        assert "public" in r.headers.get("Cache-Control", ""), url
        assert "Set-Cookie" not in r.headers, url


def test_number_prefixed_street_is_not_building_precision(client):
    r = client.get(GET_URL, query_string={"q": "3 Maja Hajnówka"})
    assert r.status_code == 200
    body = r.get_json()
    match = body["match"]
    assert match["display"] == "3 Maja, Hajnówka"
    assert match["geocode_precision"] == "street_centroid"
    assert match["confidence"] == "medium"
    assert body["is_estimate"] is True


def test_trailing_house_number_is_low_confidence(client):
    r = client.get(GET_URL, query_string={"q": "Marszałkowska 5 Warszawa"})
    assert r.status_code == 200
    body = r.get_json()
    match = body["match"]
    assert match["geocode_precision"] == "street_centroid"
    assert match["confidence"] == "low"
    assert body["is_estimate"] is True


def test_batch_requires_api_key(client):
    """Anonymous/browser-origin callers (a forged Referer reaches the
    'anonymous' tier) must NOT get 100-address batches — the B2B batch
    endpoint requires a real API key."""
    r = client.post(BATCH_URL, json={"addresses": [{"id": "x", "q": "Marszałkowska Warszawa"}]})
    assert r.status_code == 403
    assert (r.get_json() or {}).get("error") == "api_key_required"
