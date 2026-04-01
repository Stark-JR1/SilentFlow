from __future__ import annotations


def test_reset_password_page_renders(app_client):
    response = app_client.client.get("/auth/reset-password")
    assert response.status_code == 200
    assert "Redefinir senha" in response.text


def test_reset_password_confirm_page_renders(app_client):
    response = app_client.client.get("/auth/reset-password/confirm")
    assert response.status_code == 200
    assert "Definir nova senha" in response.text


def test_reset_password_sends_email_with_redirect(app_client):
    response = app_client.client.post("/auth/reset-password", data={"email": "user@example.com"})
    assert response.status_code == 200

    options = app_client.supabase.auth.last_reset_options or {}
    assert options.get("redirect_to") == "http://localhost:8000/auth/reset-password/confirm"


def test_reset_password_confirm_rejects_mismatch(app_client):
    response = app_client.client.post(
        "/auth/reset-password/confirm",
        data={
            "access_token": "token-123",
            "refresh_token": "refresh-123",
            "password": "senha123",
            "confirm": "senha999",
        },
    )
    assert response.status_code == 400


def test_reset_password_confirm_rejects_short_password(app_client):
    response = app_client.client.post(
        "/auth/reset-password/confirm",
        data={
            "access_token": "token-123",
            "refresh_token": "refresh-123",
            "password": "abc1234",
            "confirm": "abc1234",
        },
    )
    assert response.status_code == 400


def test_reset_password_confirm_rejects_missing_number(app_client):
    response = app_client.client.post(
        "/auth/reset-password/confirm",
        data={
            "access_token": "token-123",
            "refresh_token": "refresh-123",
            "password": "senhasemnumero",
            "confirm": "senhasemnumero",
        },
    )
    assert response.status_code == 400


def test_reset_password_confirm_rejects_missing_letter(app_client):
    response = app_client.client.post(
        "/auth/reset-password/confirm",
        data={
            "access_token": "token-123",
            "refresh_token": "refresh-123",
            "password": "12345678",
            "confirm": "12345678",
        },
    )
    assert response.status_code == 400


def test_reset_password_confirm_updates_password(app_client):
    response = app_client.client.post(
        "/auth/reset-password/confirm",
        data={
            "access_token": "token-123",
            "refresh_token": "refresh-123",
            "password": "senha1234",
            "confirm": "senha1234",
        },
    )
    assert response.status_code == 200
    assert app_client.supabase.auth.updated_password == "senha1234"
