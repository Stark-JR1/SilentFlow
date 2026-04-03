def test_jwt_expired_on_api_dashboard_redirects_instead_of_500(logged_client, monkeypatch):
    from fastapi import HTTPException
    from app.routers import api as api_router

    def broken_client(_request):
        raise HTTPException(status_code=401, detail="JWT expired")

    monkeypatch.setattr(api_router, "get_authed_client", broken_client)

    response = logged_client.client.get("/api/dashboard", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"


def test_family_api_returns_none_instead_of_crashing_without_group(logged_client):
    response = logged_client.client.get("/api/family")

    assert response.status_code == 200
    assert response.json() is None


def test_supabase_jwt_expired_on_dashboard_redirects_to_login(logged_client, monkeypatch):
    from postgrest.exceptions import APIError
    from app.services import db

    def broken_get_month_transactions(_client, _user_id, _month):
        raise APIError(
            {
                "code": "PGRST303",
                "details": None,
                "hint": None,
                "message": "JWT expired",
            }
        )

    monkeypatch.setattr(db, "get_month_transactions", broken_get_month_transactions)

    response = logged_client.client.get("/dashboard", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"
