import pytest
from app.intelligence.profile import build_user_behavior_profile
from app.intelligence.alerts import generate_intelligence_alerts


def test_build_user_behavior_profile():
    """Test building user behavior profile from transactions."""
    transactions = [
        {
            "date": "2024-01-15",
            "amount": 5000.00,
            "type": "income",
            "category_id": "cat-salary",
            "account_id": "acc-1",
            "card_id": None,
        },
        {
            "date": "2024-01-20",
            "amount": -150.00,
            "type": "expense",
            "category_id": "cat-food",
            "account_id": "acc-1",
            "card_id": None,
        },
        {
            "date": "2024-02-15",
            "amount": 5000.00,
            "type": "income",
            "category_id": "cat-salary",
            "account_id": "acc-1",
            "card_id": None,
        },
        {
            "date": "2024-02-25",
            "amount": -200.00,
            "type": "expense",
            "category_id": "cat-utilities",
            "account_id": "acc-1",
            "card_id": None,
        },
    ]

    profile = build_user_behavior_profile(transactions)

    assert profile["avg_monthly_income"] == 5000.00
    assert profile["avg_monthly_expense"] == 175.00
    assert profile["avg_monthly_savings"] == 4825.00
    assert profile["active_months_count"] == 2
    assert profile["top_category_id"] == "cat-utilities"  # utilities has higher total expense


def test_generate_intelligence_alerts():
    """Test generating intelligence alerts."""
    current_month_transactions = [
        {
            "date": "2024-03-15",
            "amount": -500.00,
            "type": "expense",
            "category_id": "cat-food",
            "account_id": "acc-1",
            "card_id": None,
            "description": "Restaurante caro",
        }
    ]

    previous_month_transactions = [
        {
            "date": "2024-02-15",
            "amount": -150.00,
            "type": "expense",
            "category_id": "cat-food",
            "account_id": "acc-1",
            "card_id": None,
            "description": "Restaurante normal",
        }
    ]

    user_profile = {
        "avg_monthly_expense": 200.00,
        "top_category_id": "cat-food",
    }

    alerts = generate_intelligence_alerts(
        current_month_transactions=current_month_transactions,
        previous_month_transactions=previous_month_transactions,
        user_profile=user_profile,
        cards_usage=[],
    )

    assert len(alerts) > 0
    assert any(alert["alert_type"] == "category_spike" for alert in alerts)


def test_generate_alerts_empty_data():
    """Test generating alerts with empty data."""
    alerts = generate_intelligence_alerts(
        current_month_transactions=[],
        previous_month_transactions=[],
        user_profile=None,
        cards_usage=[],
    )

    assert len(alerts) == 0


def test_build_user_behavior_profile_counts_month_with_transfer_as_active():
    transactions = [
        {
            "date": "2024-01-10",
            "amount": 1200.00,
            "type": "income",
            "category_id": "cat-income",
            "account_id": "acc-1",
            "card_id": None,
        },
        {
            "date": "2024-02-05",
            "amount": 300.00,
            "type": "transfer",
            "category_id": None,
            "account_id": "acc-1",
            "card_id": None,
        },
    ]

    profile = build_user_behavior_profile(transactions)

    assert profile["active_months_count"] == 2
    assert profile["avg_monthly_income"] == 600.00
    assert profile["avg_monthly_expense"] == 0.00
    assert profile["avg_monthly_savings"] == 600.00
