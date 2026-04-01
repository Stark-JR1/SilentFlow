from datetime import date


def test_recurring_page_renders(logged_client):
    response = logged_client.client.get("/recurring")

    assert response.status_code == 200


def test_create_pause_and_delete_recurring(logged_client):
    client = logged_client.client

    create = client.post(
        "/api/recurring",
        json={
            "category_id": "cat-expense",
            "type": "expense",
            "scope": "personal",
            "description": "Academia",
            "amount": 79.9,
            "frequency": "monthly",
            "start_date": date.today().isoformat(),
            "day_of_month": 5,
        },
    )
    recurring_id = create.json()["id"]

    pause = client.patch(f"/api/recurring/{recurring_id}")
    delete = client.delete(f"/api/recurring/{recurring_id}")
    listing = client.get("/api/recurring")

    assert create.status_code == 201
    assert pause.status_code == 200
    assert pause.json()["is_active"] is False
    assert delete.status_code == 204
    assert all(item["id"] != recurring_id for item in listing.json())


def test_paused_recurring_moves_out_of_active_section(logged_client):
    client = logged_client.client

    create = client.post(
        "/api/recurring",
        json={
            "category_id": "cat-expense",
            "type": "expense",
            "scope": "personal",
            "description": "Internet Casa",
            "amount": 129.9,
            "frequency": "monthly",
            "start_date": date.today().isoformat(),
            "day_of_month": 10,
        },
    )
    recurring_id = create.json()["id"]

    pause = client.patch(f"/api/recurring/{recurring_id}")
    page = client.get("/recurring")

    assert pause.status_code == 200
    assert "Lancamentos pausados" in page.text
    assert "Nenhum lancamento recorrente ativo." not in page.text
    assert "Internet Casa" in page.text
