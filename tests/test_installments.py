from datetime import date


def test_card_installments_create_multiple_transactions_and_invoices(logged_client):
    client = logged_client.client

    response = client.post(
        "/api/transactions",
        json={
            "category_id": "cat-expense",
            "type": "expense",
            "scope": "personal",
            "payment_method": "card",
            "card_id": "card-1",
            "description": "Curso parcelado",
            "amount": 200.0,
            "date": date.today().replace(day=15).isoformat(),
            "is_installment": True,
            "installment_total": 3,
            "total_installments": 3,
            "tags": [],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 3
    assert len({item["installment_group_id"] for item in payload}) == 1
    assert [item["installment_number"] for item in payload] == [1, 2, 3]
    assert all(item["invoice_id"] for item in payload)
    assert len(logged_client.state["card_invoices"]) >= 2
