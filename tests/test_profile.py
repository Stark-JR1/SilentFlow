def test_profile_menu_route_renders_page(logged_client):
    response = logged_client.client.get("/profile")
    assert response.status_code == 200
    assert "Perfil" in response.text
    assert "Conta, preferências e segurança" in response.text


def test_profile_page_does_not_redirect_to_insights(logged_client):
    response = logged_client.client.get("/profile", follow_redirects=False)
    assert response.status_code == 200
    assert "/settings/intelligence" not in response.text


def test_authenticated_user_can_load_own_profile(logged_client):
    response = logged_client.client.get("/api/profile")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "user-1"
    assert payload["email"] == "user@example.com"


def test_user_can_update_profile_name_and_email(logged_client):
    response = logged_client.client.patch(
        "/api/profile",
        json={
            "full_name": "Usuario Atualizado",
            "email": "novo-email@example.com",
            "currency": "USD",
            "default_scope": "shared",
            "week_start": "sunday",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["full_name"] == "Usuario Atualizado"
    assert payload["email"] == "novo-email@example.com"
    assert payload["currency"] == "USD"
    assert payload["default_scope"] == "shared"
    assert payload["week_start"] == "sunday"


def test_user_cannot_edit_other_user_profile(logged_client, monkeypatch):
    from app.services import db

    def guard_update(_client, user, payload):
        assert user["id"] == "user-1"
        assert "id" not in payload
        assert "user_id" not in payload
        return {"id": user["id"], "full_name": "ok", "email": user["email"]}

    monkeypatch.setattr(db, "update_user_profile", guard_update)
    response = logged_client.client.patch(
        "/api/profile",
        json={"id": "user-2", "user_id": "user-2", "full_name": "Tentativa"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "user-1"


def test_profile_password_reset_flow_available(logged_client):
    response = logged_client.client.post("/api/profile/password-reset")
    assert response.status_code == 200
    assert response.json()["success"] is True
