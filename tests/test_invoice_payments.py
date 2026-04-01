from datetime import date


def test_invoice_payment_reduces_balance_and_updates_invoice_without_duplicate_expense(logged_client):
    client = logged_client.client

    purchase = client.post(
        "/api/transactions",
        json={
            "category_id": "cat-expense",
            "type": "expense",
            "scope": "personal",
            "payment_method": "card",
            "card_id": "card-1",
            "description": "Notebook",
            "amount": 400.0,
            "date": date.today().isoformat(),
            "tags": [],
        },
    )
    invoice_id = purchase.json()["invoice_id"]
    starting_balance = logged_client.state["accounts"][0]["current_balance"]
    starting_tx_count = len(logged_client.state["transactions"])

    payment = client.post(
        "/api/invoices/pay",
        json={
            "invoice_id": invoice_id,
            "account_id": "acc-1",
            "amount": 400.0,
            "payment_date": date.today().isoformat(),
            "notes": "Quitacao fatura",
        },
    )

    assert payment.status_code == 200
    assert payment.json()["paid_amount"] == 400.0
    assert payment.json()["status"] == "paid"
    assert logged_client.state["accounts"][0]["current_balance"] == starting_balance - 400.0
    assert len(logged_client.state["transactions"]) == starting_tx_count
