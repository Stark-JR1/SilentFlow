from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime


def _normalize_reference_month(reference_month: str | None) -> str | None:
    if not reference_month:
        return None

    raw_value = str(reference_month).strip()
    if not raw_value:
        return None
    if len(raw_value) == 7:
        raw_value = f"{raw_value}-01"

    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00")).date()
    except ValueError:
        parsed = date.fromisoformat(raw_value)

    return parsed.replace(day=1).isoformat()


def generate_intelligence_alerts(
    current_month_transactions: list[dict],
    previous_month_transactions: list[dict],
    user_profile: dict,
    cards_usage: list[dict] | None = None,
    reference_month: str | None = None,
) -> list[dict]:
    alerts = []
    user_profile = user_profile or {}
    reference_month = _normalize_reference_month(reference_month)

    current_cat = defaultdict(float)
    previous_cat = defaultdict(float)

    for tx in current_month_transactions:
        if tx.get("type") == "expense" and tx.get("category_id"):
            current_cat[tx["category_id"]] += abs(float(tx.get("amount") or 0))

    for tx in previous_month_transactions:
        if tx.get("type") == "expense" and tx.get("category_id"):
            previous_cat[tx["category_id"]] += abs(float(tx.get("amount") or 0))

    for category_id, current_total in current_cat.items():
        prev_total = previous_cat.get(category_id, 0)
        if prev_total > 0 and current_total > prev_total * 1.20:
            variation = round(((current_total - prev_total) / prev_total) * 100, 1)
            alerts.append({
                "alert_type": "category_spike",
                "severity": "warning" if variation < 50 else "critical",
                "title": "Gasto acima do padrao",
                "message": f"Essa categoria subiu {variation}% em relacao ao mes anterior.",
                "reference_month": reference_month,
                "category_id": category_id,
                "amount": round(current_total, 2),
                "metadata": {
                    "previous_total": round(prev_total, 2),
                    "current_total": round(current_total, 2),
                    "variation_pct": variation,
                },
            })

    avg_value = float(user_profile.get("avg_transaction_value") or 0)
    if avg_value > 0:
        for tx in current_month_transactions:
            value = abs(float(tx.get("amount") or 0))
            if value > avg_value * 2.5:
                alerts.append({
                    "alert_type": "unusual_transaction",
                    "severity": "warning",
                    "title": "Transacao fora do padrao",
                    "message": "Esse valor esta bem acima da sua media usual de lancamentos.",
                    "reference_month": reference_month,
                    "transaction_id": tx.get("id"),
                    "category_id": tx.get("category_id"),
                    "account_id": tx.get("account_id"),
                    "card_id": tx.get("card_id"),
                    "amount": round(value, 2),
                    "metadata": {
                        "avg_transaction_value": round(avg_value, 2),
                    },
                })

    avg_income = float(user_profile.get("avg_monthly_income") or 0)
    avg_expense = float(user_profile.get("avg_monthly_expense") or 0)
    if avg_income > 0:
        savings_rate = (avg_income - avg_expense) / avg_income
        if savings_rate < 0.10:
            alerts.append({
                "alert_type": "low_savings_rate",
                "severity": "warning",
                "title": "Taxa de poupanca baixa",
                "message": "Seu padrao recente indica pouca sobra no mes.",
                "reference_month": reference_month,
                "amount": round(avg_income - avg_expense, 2),
                "metadata": {
                    "avg_income": round(avg_income, 2),
                    "avg_expense": round(avg_expense, 2),
                    "savings_rate": round(savings_rate, 4),
                },
            })

    for card in cards_usage or []:
        used = float(card.get("used") or 0)
        limit_ = float(card.get("limit") or 0)
        if limit_ > 0 and used / limit_ >= 0.80:
            ratio = round((used / limit_) * 100, 1)
            alerts.append({
                "alert_type": "high_card_usage",
                "severity": "critical" if ratio >= 95 else "warning",
                "title": "Uso alto do cartao",
                "message": f"Esse cartao esta usando {ratio}% do limite.",
                "reference_month": reference_month,
                "card_id": card.get("card_id"),
                "amount": round(used, 2),
                "metadata": {
                    "used": round(used, 2),
                    "limit": round(limit_, 2),
                    "usage_pct": ratio,
                    "name": card.get("name"),
                },
            })

    return alerts
