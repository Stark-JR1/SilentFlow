def test_accounts_page_renders(logged_client):
    response = logged_client.client.get("/accounts")

    assert response.status_code == 200


def test_accounts_create_and_list(logged_client):
    client = logged_client.client

    create = client.post(
        "/api/accounts",
        json={
            "name": "Carteira",
            "type": "wallet",
            "initial_balance": 50.0,
            "is_shared": False,
        },
    )
    listing = client.get("/api/accounts")

    assert create.status_code == 201
    assert create.json()["name"] == "Carteira"
    assert len(listing.json()) == 2


def test_accounts_reject_invalid_enum(logged_client):
    response = logged_client.client.post(
        "/api/accounts",
        json={"name": "Teste", "type": "invalid-type", "initial_balance": 10},
    )

    assert response.status_code == 422
