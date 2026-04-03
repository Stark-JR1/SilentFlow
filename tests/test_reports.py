def test_reports_page_renders(logged_client):
    response = logged_client.client.get("/reports")

    assert response.status_code == 200


def test_reports_page_renders_without_transactions(logged_client):
    logged_client.state["transactions"].clear()

    response = logged_client.client.get("/reports")

    assert response.status_code == 200


def test_dashboard_api_returns_json_when_data_is_empty(logged_client):
    logged_client.state["transactions"].clear()
    logged_client.state["accounts"].clear()
    logged_client.state["cards"].clear()
    logged_client.state["goals"].clear()

    response = logged_client.client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["recent_txs"] == []
    assert payload["accounts"] == []
    assert payload["cards"] == []
