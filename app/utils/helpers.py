from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from babel.numbers import format_currency as babel_format
from typing import List, Optional
import calendar


# ---- CURRENCY ----------------------------------------------

def fmt_currency(value: float, currency: str = "BRL", locale: str = "pt_BR") -> str:
    """Format a value as Brazilian Real currency."""
    try:
        return babel_format(abs(value), currency, locale=locale)
    except Exception:
        return f"R$ {abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_compact_currency(value: float) -> str:
    """Compact format: R$ 1,2k / R$ 3,5M."""
    abs_val = abs(value)
    prefix = "-" if value < 0 else ""
    if abs_val >= 1_000_000:
        return f"{prefix}R$ {abs_val/1_000_000:.1f}M"
    if abs_val >= 1_000:
        return f"{prefix}R$ {abs_val/1_000:.1f}k"
    return fmt_currency(value)


# ---- DATES -------------------------------------------------

def get_month_range(ref: date = None):
    """Returns (start, end) dates for the given month."""
    if ref is None:
        ref = date.today()
    start = ref.replace(day=1)
    last_day = calendar.monthrange(ref.year, ref.month)[1]
    end = ref.replace(day=last_day)
    return start, end


def get_last_n_months(n: int = 6) -> list[date]:
    """Returns list of first-day-of-month dates for last N months."""
    today = date.today()
    return [
        (today - relativedelta(months=i)).replace(day=1)
        for i in range(n - 1, -1, -1)
    ]


def format_month_label(d: date, locale: str = "pt_BR") -> str:
    MONTHS_PT = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                 "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    return f"{MONTHS_PT[d.month - 1]}/{str(d.year)[2:]}"


def format_date_br(d) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%d/%m/%Y")


def next_recurrence_date(current: date, frequency: str, day_of_month: int = None) -> date:
    from app.schemas.models import RecurrenceFrequency
    if frequency == RecurrenceFrequency.daily:
        return current + relativedelta(days=1)
    elif frequency == RecurrenceFrequency.weekly:
        return current + relativedelta(weeks=1)
    elif frequency == RecurrenceFrequency.biweekly:
        return current + relativedelta(weeks=2)
    elif frequency == RecurrenceFrequency.monthly:
        next_d = current + relativedelta(months=1)
        if day_of_month:
            last = calendar.monthrange(next_d.year, next_d.month)[1]
            next_d = next_d.replace(day=min(day_of_month, last))
        return next_d
    elif frequency == RecurrenceFrequency.yearly:
        return current + relativedelta(years=1)
    return current + relativedelta(months=1)


# ---- KPI CALCULATIONS --------------------------------------

def calculate_kpis(transactions: list, consolidated_balance: float, month: date = None) -> dict:
    if month is None:
        month = date.today()

    start, end = get_month_range(month)

    month_txs = [
        t for t in transactions
        if t.get("type") != "transfer"
        and start <= date.fromisoformat(t["date"]) <= end
    ]

    total_income   = sum(t["amount"] for t in month_txs if t["type"] == "income")
    total_expenses = sum(t["amount"] for t in month_txs if t["type"] == "expense")
    net_result     = total_income - total_expenses
    savings_rate   = (net_result / total_income * 100) if total_income > 0 else 0.0

    MONTHS_PT = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
                 "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

    return {
        "total_income":          round(total_income, 2),
        "total_expenses":        round(total_expenses, 2),
        "net_result":            round(net_result, 2),
        "consolidated_balance":  round(consolidated_balance, 2),
        "savings_rate":          round(savings_rate, 1),
        "month":                 f"{MONTHS_PT[month.month - 1]} {month.year}",
    }


def calculate_category_summary(transactions: list) -> list:
    """Groups expense transactions by category and calculates percentages."""
    expenses = [t for t in transactions if t.get("type") == "expense"]
    total    = sum(t["amount"] for t in expenses)

    by_cat: dict = {}
    for tx in expenses:
        cat  = tx.get("category") or {}
        name = cat.get("name", "Sem categoria")
        if name not in by_cat:
            by_cat[name] = {
                "category_name":  name,
                "category_icon":  cat.get("icon", "📦"),
                "category_color": cat.get("color", "#6c63ff"),
                "total": 0.0,
                "count": 0,
            }
        by_cat[name]["total"] += tx["amount"]
        by_cat[name]["count"] += 1

    result = []
    for item in by_cat.values():
        item["percentage"] = round(item["total"] / total * 100, 1) if total > 0 else 0.0
        item["total"]      = round(item["total"], 2)
        result.append(item)

    return sorted(result, key=lambda x: x["total"], reverse=True)[:8]


# ---- INSIGHTS ENGINE (rule-based) --------------------------

def generate_insights(
    current_txs: list,
    prev_txs: list,
    goals: list,
    cards: list,
) -> list:
    insights = []

    # --- Category overspend ---
    def by_cat(txs):
        d = {}
        for t in txs:
            if t.get("type") == "expense" and t.get("category_id"):
                cid = t["category_id"]
                d[cid] = d.get(cid, {"total": 0.0, "name": t.get("category", {}).get("name", "?")})
                d[cid]["total"] += t["amount"]
        return d

    curr_cat = by_cat(current_txs)
    prev_cat = by_cat(prev_txs)

    for cid, curr in curr_cat.items():
        prev = prev_cat.get(cid, {}).get("total", 0)
        if prev > 0 and curr["total"] > prev * 1.2:
            pct = round((curr["total"] - prev) / prev * 100)
            insights.append({
                "type": "warning", "icon": "⚠",
                "title": f"{curr['name']} +{pct}% vs mês anterior",
                "description": f"Atual: {fmt_currency(curr['total'])} · Anterior: {fmt_currency(prev)}",
            })

    # --- Card near limit ---
    for card in cards:
        limit = float(card.get("credit_limit", 0))
        avail = float(card.get("available_limit", 0))
        if limit > 0:
            used_pct = (limit - avail) / limit * 100
            if used_pct >= 80:
                insights.append({
                    "type": "warning", "icon": "💳",
                    "title": f"{card['name']} em {used_pct:.0f}% do limite",
                    "description": f"Disponível: {fmt_currency(avail)}",
                })

    # --- Goal progress ---
    for goal in goals:
        if goal.get("is_completed"):
            continue
        target  = float(goal.get("target_amount", 0))
        current = float(goal.get("current_amount", 0))
        if target > 0:
            pct = current / target * 100
            if pct >= 80:
                insights.append({
                    "type": "success", "icon": "🎯",
                    "title": f"Meta \"{goal['name']}\" em {pct:.0f}%",
                    "description": f"Faltam {fmt_currency(target - current)} para concluir.",
                })

    # --- Savings rate ---
    income   = sum(t["amount"] for t in current_txs if t.get("type") == "income")
    expenses = sum(t["amount"] for t in current_txs if t.get("type") == "expense")
    if income > 0:
        rate = (income - expenses) / income * 100
        if rate >= 20:
            insights.append({
                "type": "success", "icon": "↗",
                "title": f"Taxa de poupança em {rate:.1f}%",
                "description": "Parabéns! Poupando acima de 20% da renda.",
            })
        elif rate < 5:
            insights.append({
                "type": "warning", "icon": "📉",
                "title": "Taxa de poupança abaixo de 5%",
                "description": "Revise os gastos para aumentar a margem.",
            })

    return insights[:5]


# ---- GOAL HELPERS ------------------------------------------

def goal_percentage(goal: dict) -> int:
    target  = float(goal.get("target_amount", 1))
    current = float(goal.get("current_amount", 0))
    return min(100, round(current / target * 100)) if target > 0 else 0


# ---- LABELS ------------------------------------------------

ACCOUNT_TYPE_LABELS = {
    "checking":   "Conta Corrente",
    "savings":    "Poupança",
    "wallet":     "Carteira",
    "investment": "Investimentos",
    "shared":     "Compartilhada",
}

FREQUENCY_LABELS = {
    "daily":    "Diário",
    "weekly":   "Semanal",
    "biweekly": "Quinzenal",
    "monthly":  "Mensal",
    "yearly":   "Anual",
}
