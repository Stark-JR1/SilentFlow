def test_family_page_handles_user_without_group(logged_client):
    response = logged_client.client.get("/family")

    assert response.status_code == 200


def test_alerts_page_handles_empty_notifications(logged_client):
    logged_client.state["notifications"].clear()

    response = logged_client.client.get("/alerts")

    assert response.status_code == 200


def test_cards_page_handles_no_cards(logged_client):
    logged_client.state["cards"].clear()

    response = logged_client.client.get("/cards")

    assert response.status_code == 200


def test_recurring_page_handles_empty_list(logged_client):
    logged_client.state["recurring"].clear()

    response = logged_client.client.get("/recurring")

    assert response.status_code == 200
