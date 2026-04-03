def test_root_redirects_cleanly(app_client):
    response = app_client.client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"


def test_public_pages_load_without_500(app_client):
    client = app_client.client

    assert client.get("/auth/login").status_code == 200
    assert client.get("/auth/register").status_code == 200
    assert client.get("/auth/reset-password").status_code == 200


def test_not_found_and_method_not_allowed_are_handled(app_client):
    client = app_client.client

    assert client.get("/rota-que-nao-existe").status_code == 404
    assert client.post("/dashboard").status_code == 405
    assert client.get("/api/rota-que-nao-existe").status_code == 404
