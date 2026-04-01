from datetime import date


def test_boleto_pending_then_settle_impacts_balance_only_on_payment(logged_client):
    client = logged_client.client
    starting_balance = logged_client.state["accounts"][0]["current_balance"]

    create = client.post(
        "/api/transactions",
        json={
            "category_id": "cat-expense",
            "type": "expense",
            "scope": "personal",
            "payment_method": "boleto",
            "status": "pending",
            "description": "Conta de luz",
            "amount": 120.0,
            "date": date.today().isoformat(),
            "due_date": date.today().isoformat(),
            "tags": [],
        },
    )

    assert create.status_code == 201
    assert create.json()["status"] == "pending"
    assert logged_client.state["accounts"][0]["current_balance"] == starting_balance

    settle = client.post(
        f"/api/transactions/{create.json()['id']}/settle-boleto",
        json={
            "account_id": "acc-1",
            "payment_date": date.today().isoformat(),
            "notes": "Pago no banco",
        },
    )

    assert settle.status_code == 200
    assert settle.json()["status"] == "paid"
    assert logged_client.state["accounts"][0]["current_balance"] == starting_balance - 120.0
