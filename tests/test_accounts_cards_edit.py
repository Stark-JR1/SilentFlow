def test_accounts_update_endpoint_updates_account(logged_client):
    response = logged_client.client.patch(
        "/api/accounts/acc-1",
        json={"name": "Conta Atualizada", "bank_name": "Banco Novo"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Conta Atualizada"
    assert payload["bank_name"] == "Banco Novo"


def test_accounts_update_endpoint_returns_404_for_missing_account(logged_client):
    response = logged_client.client.patch(
        "/api/accounts/acc-missing",
        json={"name": "Conta X"},
    )

    assert response.status_code == 404


def test_accounts_delete_endpoint_soft_deletes_account(logged_client):
    response = logged_client.client.delete("/api/accounts/acc-1")

    assert response.status_code == 204
    assert logged_client.state["accounts"][0]["deleted_at"] == "deleted"


def test_cards_update_endpoint_updates_card(logged_client):
    response = logged_client.client.patch(
        "/api/cards/card-1",
        json={"name": "Cartão Atualizado", "credit_limit": 3500},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Cartão Atualizado"
    assert float(payload["credit_limit"]) == 3500


def test_cards_update_endpoint_returns_404_for_missing_card(logged_client):
    response = logged_client.client.patch(
        "/api/cards/card-missing",
        json={"name": "Cartão X"},
    )

    assert response.status_code == 404


def test_cards_delete_endpoint_soft_deletes_card(logged_client):
    response = logged_client.client.delete("/api/cards/card-1")

    assert response.status_code == 204
    assert logged_client.state["cards"][0]["deleted_at"] == "deleted"
