from fastapi import HTTPException


def test_dashboard_and_related_pages_render_when_logged_in(logged_client):
    client = logged_client.client

    for path in [
        "/dashboard",
        "/transactions",
        "/accounts",
        "/cards",
        "/goals",
        "/reports",
    ]:
        response = client.get(path)
        assert response.status_code == 200, path


def test_dashboard_handles_empty_state_without_breaking(logged_client):
    state = logged_client.state
    state["transactions"].clear()
    state["accounts"].clear()
    state["cards"].clear()
    state["goals"].clear()
    state["notifications"].clear()

    dashboard = logged_client.client.get("/dashboard")
    reports = logged_client.client.get("/reports")

    assert dashboard.status_code == 200
    assert "Nenhuma transação este mês." in dashboard.text
    assert reports.status_code == 200


def test_dashboard_invalid_month_returns_422_not_500(logged_client):
    response = logged_client.client.get("/api/dashboard?month=mes-invalido")

    assert response.status_code == 422
    assert "month inválido" in response.text


def test_expired_or_invalid_token_does_not_break_dashboard(logged_client, monkeypatch):
    from app.routers import pages as pages_router

    def broken_client(_request):
        raise HTTPException(status_code=401, detail="JWT expired")

    monkeypatch.setattr(pages_router, "get_authed_client", broken_client)

    response = logged_client.client.get("/dashboard", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"
