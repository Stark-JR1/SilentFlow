from datetime import date


def test_account_and_pix_require_account_and_reduce_balance(logged_client):
    client = logged_client.client
    starting_balance = logged_client.state["accounts"][0]["current_balance"]

    account_resp = client.post(
        "/api/transactions",
        json={
            "category_id": "cat-expense",
            "account_id": "acc-1",
            "type": "expense",
            "scope": "personal",
            "payment_method": "account",
            "description": "Mercado conta",
            "amount": 100.0,
            "date": date.today().isoformat(),
            "tags": [],
        },
    )
    pix_resp = client.post(
        "/api/transactions",
        json={
            "category_id": "cat-expense",
            "account_id": "acc-1",
            "type": "expense",
            "scope": "personal",
            "payment_method": "pix",
            "description": "Mercado pix",
            "amount": 50.0,
            "date": date.today().isoformat(),
            "tags": [],
        },
    )
    missing_account = client.post(
        "/api/transactions",
        json={
            "category_id": "cat-expense",
            "type": "expense",
            "scope": "personal",
            "payment_method": "pix",
            "description": "Sem conta",
            "amount": 10.0,
            "date": date.today().isoformat(),
            "tags": [],
        },
    )

    assert account_resp.status_code == 201
    assert pix_resp.status_code == 201
    assert missing_account.status_code == 400
    assert logged_client.state["accounts"][0]["current_balance"] == starting_balance - 150.0
