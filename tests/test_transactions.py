from datetime import date


def test_transactions_page_renders_with_empty_filters(logged_client):
    response = logged_client.client.get("/transactions?type=&scope=&search=")

    assert response.status_code == 200


def test_transactions_invalid_date_filter_returns_422(logged_client):
    response = logged_client.client.get("/api/transactions?start_date=32-13-2026")

    assert response.status_code == 422
    assert "start_date inválida" in response.text


def test_transactions_crud_flow(logged_client):
    client = logged_client.client

    create = client.post(
        "/api/transactions",
        json={
            "category_id": "cat-expense",
            "account_id": "acc-1",
            "type": "expense",
            "scope": "personal",
            "description": "Farmacia",
            "amount": 89.9,
            "date": date.today().isoformat(),
            "notes": "Compra rapida",
            "tags": [],
        },
    )
    tx_id = create.json()["id"]

    listing = client.get("/api/transactions").json()
    update = client.patch(
        f"/api/transactions/{tx_id}",
        json={"description": "Farmacia atualizada"},
    )
    delete = client.delete(f"/api/transactions/{tx_id}")
    delete_again = client.delete(f"/api/transactions/{tx_id}")
    after_delete = client.get("/api/transactions").json()

    assert create.status_code == 201
    assert listing["count"] == 3
    assert update.status_code == 200
    assert update.json()["description"] == "Farmacia atualizada"
    assert delete.status_code == 204
    assert delete_again.status_code == 204
    assert after_delete["count"] == 2


def test_transactions_reject_invalid_amount(logged_client):
    response = logged_client.client.post(
        "/api/transactions",
        json={
            "category_id": "cat-expense",
            "account_id": "acc-1",
            "type": "expense",
            "scope": "personal",
            "description": "Erro",
            "amount": -1,
            "date": date.today().isoformat(),
            "tags": [],
        },
    )

    assert response.status_code == 422
