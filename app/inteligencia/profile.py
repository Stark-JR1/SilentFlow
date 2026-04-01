from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from statistics import mean
from typing import Optional


def month_start(dt: date) -> date:
    return dt.replace(day=1)


def build_user_behavior_profile(transactions: list[dict]) -> dict:
    if not transactions:
        return {
            "avg_monthly_income": 0,
            "avg_monthly_expense": 0,
            "avg_monthly_savings": 0,
            "avg_transaction_value": 0,
            "recurring_transactions_count": 0,
            "active_months_count": 0,
            "top_category_id": None,
            "top_category_share": 0,
            "most_used_account_id": None,
            "most_used_card_id": None,
        }

    monthly_income = defaultdict(float)
    monthly_expense = defaultdict(float)
    category_totals = defaultdict(float)
    account_counter = Counter()
    card_counter = Counter()
    values = []

    for tx in transactions:
        tx_date = tx.get("date")
        if not tx_date:
            continue
        ref = str(tx_date)[:7]  # YYYY-MM
        amount = float(tx.get("amount") or 0)
        tx_type = tx.get("type")
        category_id = tx.get("category_id")
        account_id = tx.get("account_id")
        card_id = tx.get("card_id")

        values.append(abs(amount))

        if tx_type == "income":
            monthly_income[ref] += amount
        elif tx_type == "expense":
            monthly_expense[ref] += abs(amount)

        if category_id and tx_type == "expense":
            category_totals[category_id] += abs(amount)

        if account_id:
            account_counter[account_id] += 1

        if card_id:
            card_counter[card_id] += 1

    months = sorted(set(monthly_income.keys()) | set(monthly_expense.keys()))
    avg_income = mean(monthly_income[m] for m in months) if months else 0
    avg_expense = mean(monthly_expense[m] for m in months) if months else 0
    avg_savings = avg_income - avg_expense

    total_expense = sum(category_totals.values())
    top_category_id = None
    top_category_share = 0
    if total_expense > 0 and category_totals:
        top_category_id, top_value = max(category_totals.items(), key=lambda x: x[1])
        top_category_share = round(top_value / total_expense, 4)

    return {
        "avg_monthly_income": round(avg_income, 2),
        "avg_monthly_expense": round(avg_expense, 2),
        "avg_monthly_savings": round(avg_savings, 2),
        "avg_transaction_value": round(mean(values), 2) if values else 0,
        "recurring_transactions_count": 0,  # recurring detection not included in this profile summary yet
        "active_months_count": len(months),
        "top_category_id": top_category_id,
        "top_category_share": top_category_share,
        "most_used_account_id": account_counter.most_common(1)[0][0] if account_counter else None,
        "most_used_card_id": card_counter.most_common(1)[0][0] if card_counter else None,
    }
