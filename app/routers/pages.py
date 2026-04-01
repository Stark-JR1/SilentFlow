import logging
from types import SimpleNamespace

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import date
from postgrest.exceptions import APIError
from app.core.supabase import require_auth, get_authed_client
from app.core.templates import build_templates
from app.intelligence import service as intelligence_service
from app.services import db
from app.utils.helpers import (
    calculate_kpis, calculate_category_summary, generate_insights,
    get_month_range, fmt_currency, ACCOUNT_TYPE_LABELS, FREQUENCY_LABELS
)

router    = APIRouter(tags=["pages"])
templates = build_templates()


def _get_month(request: Request) -> date:
    """Parse ?month=YYYY-MM from query params, default to today."""
    m = request.query_params.get("month")
    if m:
        try:
            return date.fromisoformat(f"{m}-01")
        except ValueError:
            pass
    return date.today().replace(day=1)


# ---- ROOT --------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/auth/login", status_code=302)


# ---- DASHBOARD ---------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: dict = Depends(require_auth)):
    client     = get_authed_client(request)
    month      = _get_month(request)
    from datetime import date as d_
    from dateutil.relativedelta import relativedelta
    prev_month = (month - relativedelta(months=1)).replace(day=1)

    current_txs  = db.get_month_transactions(client, user["id"], month)
    prev_txs     = db.get_month_transactions(client, user["id"], prev_month)
    accounts     = db.get_accounts(client, user["id"])
    cards        = db.get_credit_cards(client, user["id"])
    goals        = db.get_goals(client, user["id"])
    evolution    = db.get_monthly_evolution(client, user["id"], 6)

    consolidated = sum(float(a["current_balance"]) for a in accounts if a.get("include_in_total", True))
    kpis         = calculate_kpis(current_txs, consolidated, month)
    insights     = generate_insights(current_txs, prev_txs, goals, cards)

    start, end   = get_month_range(month)
    cat_report   = db.get_expenses_by_category(client, user["id"], start, end)

    alerts_payload = {"total": 0, "unread": 0, "critical": 0, "items": []}
    try:
        alerts_payload = intelligence_service.list_user_alerts(
            client, user["id"], include_read=False, limit=3
        ) or alerts_payload
    except Exception as exc:
        logging.warning("Dashboard intelligence fallback: alerts unavailable - %s", exc)

    alerts = SimpleNamespace(
        total=alerts_payload.get("total", 0),
        unread=alerts_payload.get("unread", 0),
        critical=alerts_payload.get("critical", 0),
        items=alerts_payload.get("items", []) or [],
    )

    return templates.TemplateResponse(request, "pages/dashboard.html", {
        "request":      request,
        "user":         user,
        "kpis":         kpis,
        "categories":   cat_report,
        "evolution":    evolution,
        "recent_txs":   current_txs[:8],
        "accounts":     accounts,
        "cards":        cards,
        "goals":        goals[:4],
        "insights":     insights,
        "alerts":       alerts,
        "month":        month,
        "fmt":          fmt_currency,
    })


# ---- TRANSACTIONS ------------------------------------------

@router.get("/transactions", response_class=HTMLResponse)
async def transactions_page(request: Request, user: dict = Depends(require_auth)):
    client     = get_authed_client(request)
    month      = _get_month(request)
    start, end = get_month_range(month)

    type_f     = request.query_params.get("type")
    scope_f    = request.query_params.get("scope")
    search_f   = request.query_params.get("search")
    account_id_f = request.query_params.get("account_id")
    page       = int(request.query_params.get("page", 1))

    result     = db.get_transactions(
        client, user["id"],
        type_       = type_f or None,
        scope       = scope_f or None,
        account_id  = account_id_f or None,
        search      = search_f or None,
        start_date  = start,
        end_date    = end,
        page        = page,
        per_page    = 30,
    )
    accounts   = db.get_accounts(client, user["id"])
    categories = db.get_categories(client, user["id"])

    return templates.TemplateResponse(request, "pages/transactions.html", {
        "request":     request,
        "user":        user,
        "result":      result,
        "accounts":    accounts,
        "categories":  categories,
        "month":       month,
        "type_f":      type_f or "",
        "scope_f":     scope_f or "",
        "search_f":    search_f or "",
        "account_id_f": account_id_f or "",
        "fmt":         fmt_currency,
    })


# ---- ACCOUNTS ----------------------------------------------

@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request, user: dict = Depends(require_auth)):
    client   = get_authed_client(request)
    accounts = db.get_accounts(client, user["id"])
    total    = sum(float(a["current_balance"]) for a in accounts if a.get("include_in_total", True))

    return templates.TemplateResponse(request, "pages/accounts.html", {
        "request":     request,
        "user":        user,
        "accounts":    accounts,
        "total":       total,
        "type_labels": ACCOUNT_TYPE_LABELS,
        "fmt":         fmt_currency,
    })


# ---- CREDIT CARDS ------------------------------------------

@router.get("/cards", response_class=HTMLResponse)
async def cards_page(request: Request, user: dict = Depends(require_auth)):
    client = get_authed_client(request)
    cards  = db.get_credit_cards(client, user["id"])

    return templates.TemplateResponse(request, "pages/cards.html", {
        "request": request,
        "user":    user,
        "cards":   cards,
        "fmt":     fmt_currency,
    })


# ---- GOALS -------------------------------------------------

@router.get("/goals", response_class=HTMLResponse)
async def goals_page(request: Request, user: dict = Depends(require_auth)):
    client = get_authed_client(request)
    goals  = db.get_goals(client, user["id"])

    return templates.TemplateResponse(request, "pages/goals.html", {
        "request": request,
        "user":    user,
        "goals":   goals,
        "fmt":     fmt_currency,
    })


# ---- RECURRING ---------------------------------------------

@router.get("/recurring", response_class=HTMLResponse)
async def recurring_page(request: Request, user: dict = Depends(require_auth)):
    client     = get_authed_client(request)
    recurring  = db.get_recurring(client, user["id"])
    categories = db.get_categories(client, user["id"])
    accounts   = db.get_accounts(client, user["id"])
    active_recurring = [row for row in recurring if row.get("is_active", True)]
    paused_recurring = [row for row in recurring if not row.get("is_active", True)]

    total_exp = sum(float(r["amount"]) for r in active_recurring if r["type"] == "expense")
    total_inc = sum(float(r["amount"]) for r in active_recurring if r["type"] == "income")

    return templates.TemplateResponse(request, "pages/recurring.html", {
        "request":          request,
        "user":             user,
        "recurring":        recurring,
        "active_recurring": active_recurring,
        "paused_recurring": paused_recurring,
        "categories":       categories,
        "accounts":         accounts,
        "total_expenses":   total_exp,
        "total_income":     total_inc,
        "frequency_labels": FREQUENCY_LABELS,
        "fmt":              fmt_currency,
    })


# ---- REPORTS -----------------------------------------------

@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, user: dict = Depends(require_auth)):
    client    = get_authed_client(request)
    month     = _get_month(request)
    start, end = get_month_range(month)

    current_txs = db.get_month_transactions(client, user["id"], month)
    evolution   = db.get_monthly_evolution(client, user["id"], 6)
    cat_report  = db.get_expenses_by_category(client, user["id"], start, end)
    accounts    = db.get_accounts(client, user["id"])

    consolidated = sum(float(a["current_balance"]) for a in accounts if a.get("include_in_total", True))
    kpis         = calculate_kpis(current_txs, consolidated, month)

    personal_exp = sum(float(t["amount"]) for t in current_txs if t["type"] == "expense" and t.get("scope") == "personal")
    shared_exp   = sum(float(t["amount"]) for t in current_txs if t["type"] == "expense" and t.get("scope") == "shared")

    return templates.TemplateResponse(request, "pages/reports.html", {
        "request":      request,
        "user":         user,
        "kpis":         kpis,
        "evolution":    evolution,
        "categories":   cat_report,
        "personal_exp": personal_exp,
        "shared_exp":   shared_exp,
        "month":        month,
        "fmt":          fmt_currency,
    })


# ---- FAMILY ------------------------------------------------

@router.get("/family", response_class=HTMLResponse)
async def family_page(request: Request, user: dict = Depends(require_auth)):
    client = get_authed_client(request)
    group  = db.get_family_group(client, user["id"])
    summary = db.get_family_summary(client, group["id"]) if group else None

    return templates.TemplateResponse(request, "pages/family.html", {
        "request": request,
        "user":    user,
        "group":   group,
        "summary": summary,
        "fmt":     fmt_currency,
    })


# ---- ALERTS ------------------------------------------------

@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request, user: dict = Depends(require_auth)):
    client = get_authed_client(request)

    resp   = (
        client.table("notifications")
        .select("*")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )
    notifications = resp.data or []
    unread        = sum(1 for n in notifications if not n.get("is_read"))

    return templates.TemplateResponse(request, "pages/alerts.html", {
        "request":       request,
        "user":          user,
        "notifications": notifications,
        "unread":        unread,
    })


# ---- IMPORTS -----------------------------------------------

@router.get("/imports", response_class=HTMLResponse)
async def imports_page(request: Request, user: dict = Depends(require_auth)):
    return templates.TemplateResponse(request, "pages/imports.html", {
        "request": request,
        "user": user,
        "supported_banks": ["Bradesco", "C6 Bank", "Sicoob", "Inter", "Nubank"],
        "supported_formats": ["XML", "OFX", "CSV", "PDF"],
    })


# ---- INTELLIGENCE ------------------------------------------

@router.get("/settings", include_in_schema=False)
async def settings_redirect(user: dict = Depends(require_auth)):
    return RedirectResponse("/settings/intelligence", status_code=302)


@router.get("/intelligence", include_in_schema=False)
async def intelligence_redirect(user: dict = Depends(require_auth)):
    return RedirectResponse("/settings/intelligence", status_code=302)

@router.get("/settings/intelligence", response_class=HTMLResponse)
async def intelligence_page(request: Request, user: dict = Depends(require_auth)):
    client = get_authed_client(request)
    try:
        settings = intelligence_service.get_user_settings(client, user["id"])
        rules = intelligence_service.list_rules(client, user["id"])
    except APIError:
        settings = intelligence_service.DEFAULT_SETTINGS.copy()
        rules = []

    profile = None
    try:
        profile = intelligence_service.get_user_profile(client, user["id"])
    except Exception as exc:
        logging.warning("Intelligence page fallback: profile unavailable - %s", exc)
        profile = None

    alerts_payload = {"total": 0, "unread": 0, "critical": 0, "items": []}
    try:
        alerts_payload = intelligence_service.list_user_alerts(
            client, user["id"], include_read=True, limit=10
        ) or alerts_payload
    except Exception as exc:
        logging.warning("Intelligence page fallback: alerts unavailable - %s", exc)

    rules_view = []
    for rule in rules:
        current = dict(rule)
        last_used_label = "Nunca"
        last_used = current.get("last_used_at")
        if last_used:
            try:
                last_dt = date.fromisoformat(str(last_used)[:10])
                days = max((date.today() - last_dt).days, 0)
                if days == 0:
                    last_used_label = "Hoje"
                elif days == 1:
                    last_used_label = "Ontem"
                elif days < 7:
                    last_used_label = f"{days} dias"
                elif days < 30:
                    last_used_label = f"{max(round(days / 7), 1)} sem"
                else:
                    last_used_label = f"{max(round(days / 30), 1)} mes"
            except ValueError:
                last_used_label = "Nunca"
        current["last_used_label"] = last_used_label
        rules_view.append(current)

    total_usage = sum(int(rule.get("usage_count") or 0) for rule in rules_view)
    avg_confidence_pct = 0
    confidence_values = [float(rule.get("confidence_score") or 0) for rule in rules_view if rule.get("confidence_score") is not None]
    if confidence_values:
        avg_confidence_pct = round(sum(confidence_values) / len(confidence_values) * 100)
    rules_stats = SimpleNamespace(
        mature_count=len([rule for rule in rules_view if int(rule.get("usage_count") or 0) > 5]),
        total_usage=total_usage,
        avg_confidence_pct=avg_confidence_pct,
    )

    alerts = SimpleNamespace(
        total=alerts_payload.get("total", 0),
        unread=alerts_payload.get("unread", 0),
        critical=alerts_payload.get("critical", 0),
        items=alerts_payload.get("items", []) or [],
    )
    profile_view = SimpleNamespace(**profile) if isinstance(profile, dict) else profile

    return templates.TemplateResponse(request, "pages/intelligence.html", {
        "request": request,
        "user": user,
        "settings": settings,
        "rules": rules_view,
        "rules_stats": rules_stats,
        "profile": profile_view,
        "alerts": alerts,
    })
