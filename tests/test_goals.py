def test_goals_page_renders_with_data(logged_client):
    response = logged_client.client.get("/goals")

    assert response.status_code == 200


def test_goals_page_renders_with_empty_state(logged_client):
    logged_client.state["goals"].clear()

    response = logged_client.client.get("/goals")

    assert response.status_code == 200


def test_goals_create_and_list(logged_client):
    client = logged_client.client

    create = client.post(
        "/api/goals",
        json={"name": "Viagem", "target_amount": 2000, "scope": "personal"},
    )
    listing = client.get("/api/goals")

    assert create.status_code == 201
    assert create.json()["name"] == "Viagem"
    assert len(listing.json()) == 2


def test_goals_reject_invalid_amount(logged_client):
    response = logged_client.client.post(
        "/api/goals",
        json={"name": "Viagem", "target_amount": 0, "scope": "personal"},
    )

    assert response.status_code == 422
