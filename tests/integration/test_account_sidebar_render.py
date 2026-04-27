def test_account_page_renders_with_sidebar(authed_client):
    r = authed_client.get("/account")
    assert r.status_code == 200, r.data
    html = r.data.decode()
    for marker in ['id="locations"','id="api-access"','id="two-factor"',
                   'account-section','account-nav-link','Saved spots',
                   'href="#locations"','href="#api-access"']:
        assert marker in html, f"missing: {marker}"
