from datetime import date


def test_card_purchase_associates_invoice_and_does_not_reduce_account_balance(logged_client):
    client = logged_client.client
    starting_balance = logged_client.state["accounts"][0]["current_balance"]

    response = client.post(
        "/api/transactions",
        json={
            "category_id": "cat-expense",
            "type": "expense",
            "scope": "personal",
            "payment_method": "card",
            "card_id": "card-1",
            "description": "Compra no cartao",
            "amount": 300.0,
            "date": date.today().isoformat(),
            "tags": [],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["invoice_id"] is not None
    assert logged_client.state["accounts"][0]["current_balance"] == starting_balance
    assert len(logged_client.state["card_invoices"]) == 1
    assert logged_client.state["card_invoices"][0]["total_amount"] == 300.0
