from datetime import date
from pathlib import Path

from app.utils.helpers import calculate_kpis, generate_insights, goal_percentage, next_recurrence_date


def test_calculate_kpis_matches_month_transactions():
    month = date(2026, 3, 1)
    transactions = [
        {"type": "income", "amount": 3000.0, "date": "2026-03-05"},
        {"type": "expense", "amount": 1200.0, "date": "2026-03-10"},
        {"type": "transfer", "amount": 999.0, "date": "2026-03-11"},
    ]

    kpis = calculate_kpis(transactions, consolidated_balance=5000.0, month=month)

    assert kpis["total_income"] == 3000.0
    assert kpis["total_expenses"] == 1200.0
    assert kpis["net_result"] == 1800.0
    assert kpis["consolidated_balance"] == 5000.0


def test_generate_insights_warns_for_card_limit_and_overspend():
    current = [
        {
            "type": "expense",
            "amount": 600.0,
            "date": "2026-03-10",
            "category_id": "cat-1",
            "category": {"name": "Mercado"},
        }
    ]
    previous = [
        {
            "type": "expense",
            "amount": 300.0,
            "date": "2026-02-10",
            "category_id": "cat-1",
            "category": {"name": "Mercado"},
        }
    ]
    goals = [{"name": "Reserva", "target_amount": 1000, "current_amount": 900, "is_completed": False}]
    cards = [{"name": "Cartao", "credit_limit": 1000, "available_limit": 100}]

    insights = generate_insights(current, previous, goals, cards)
    titles = [insight["title"] for insight in insights]

    assert any("Mercado" in title for title in titles)
    assert any("Cartao" in title for title in titles)
    assert any("Reserva" in title for title in titles)


def test_goal_percentage_caps_at_100():
    assert goal_percentage({"target_amount": 100, "current_amount": 150}) == 100


def test_next_recurrence_date_clamps_day_for_short_month():
    current = date(2026, 1, 31)
    next_date = next_recurrence_date(current, "monthly", day_of_month=31)
    assert next_date == date(2026, 2, 28)


def test_codebase_has_no_leftover_todo_or_debug_prints():
    roots = [Path("app"), Path("main.py")]
    text = "\n".join(path.read_text(encoding="utf-8") for root in roots for path in ([root] if root.is_file() else root.rglob("*.py")))

    assert "TODO" not in text
    assert "FIXME" not in text
    assert "print(" not in text
