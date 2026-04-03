def test_protected_routes_redirect_without_login(app_client):
    client = app_client.client

    dashboard = client.get("/dashboard", follow_redirects=False)
    api_dashboard = client.get("/api/dashboard", follow_redirects=False)

    assert dashboard.status_code == 302
    assert dashboard.headers["location"] == "/auth/login"
    assert api_dashboard.status_code == 302
    assert api_dashboard.headers["location"] == "/auth/login"


def test_login_logout_flow_redirects_correctly(logged_client):
    client = logged_client.client

    dashboard = client.get("/dashboard")
    logout = client.get("/auth/logout", follow_redirects=False)
    after_logout = client.get("/dashboard", follow_redirects=False)

    assert dashboard.status_code == 200
    assert logout.status_code == 302
    assert logout.headers["location"] == "/auth/login"
    assert after_logout.status_code == 302
    assert after_logout.headers["location"] == "/auth/login"


def test_login_rejects_invalid_credentials(app_client):
    response = app_client.client.post(
        "/auth/login",
        data={"email": "user@example.com", "password": "errada"},
    )

    assert response.status_code == 400
    assert "Invalid login credentials" in response.text


def test_login_rejects_missing_fields(app_client):
    response = app_client.client.post("/auth/login", data={"email": ""})

    assert response.status_code == 422


def test_register_rejects_mismatched_passwords(app_client):
    response = app_client.client.post(
        "/auth/register",
        data={
            "full_name": "Usuario Teste",
            "email": "novo@example.com",
            "password": "123456",
            "confirm": "654321",
        },
    )

    assert response.status_code == 400
    assert "As senhas não coincidem" in response.text
