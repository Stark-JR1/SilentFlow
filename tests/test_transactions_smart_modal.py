from datetime import date


def test_transactions_page_contains_premium_new_transaction_blocks(logged_client):
    response = logged_client.client.get("/transactions")

    assert response.status_code == 200
    assert "Lançamento rápido com IA" in response.text
    assert "Contexto financeiro" in response.text
    assert "Últimas transações" in response.text
    assert "Salvar e repetir" in response.text


def test_transactions_preview_endpoint_returns_projected_balance(logged_client):
    response = logged_client.client.get(
        "/api/transactions/preview",
        params={"account_id": "acc-1", "amount": 100, "type": "expense"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["current_balance"] == 800.0
    assert payload["projected_balance"] == 700.0
    assert payload["impact_status"] == "saudavel"


def test_transactions_preview_endpoint_detects_critical_impact(logged_client):
    response = logged_client.client.get(
        "/api/transactions/preview",
        params={"account_id": "acc-1", "amount": 1200, "type": "expense"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["projected_balance"] == -400.0
    assert payload["impact_status"] == "critico"


def test_transactions_quick_parse_extracts_common_fields(logged_client):
    response = logged_client.client.post(
        "/api/transactions/quick-parse",
        json={"raw_text": "mercado 120 conta principal"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["amount"] == 120.0
    assert payload["transaction_type"] == "expense"
    assert payload["account_id"] == "acc-1"
    assert payload["category_id"] == "cat-expense"


def test_transactions_quick_parse_handles_missing_category_suggestion(logged_client):
    response = logged_client.client.post(
        "/api/transactions/quick-parse",
        json={"raw_text": "coisa aleatoria 33"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["amount"] == 33.0
    assert payload["category_id"] is None


def test_transactions_recent_returns_latest_rows(logged_client):
    client = logged_client.client
    client.post(
        "/api/transactions",
        json={
            "category_id": "cat-expense",
            "account_id": "acc-1",
            "type": "expense",
            "scope": "personal",
            "description": "Compra nova",
            "amount": 12.5,
            "date": date.today().isoformat(),
            "notes": None,
            "tags": [],
        },
    )

    response = client.get("/api/transactions/recent?limit=2")
    payload = response.json()

    assert response.status_code == 200
    assert len(payload) == 2
    assert payload[0]["description"] in {"Compra nova", "Compras do mes", "Salario"}
