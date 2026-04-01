from fastapi import APIRouter, Request, Depends, HTTPException, File, Form, UploadFile
from fastapi.responses import JSONResponse
from datetime import date
from postgrest.exceptions import APIError
from app.core.supabase import get_current_user, get_authed_client
from app.intelligence import service as intelligence_service
from app.intelligence.schemas import (
    FeedbackRequest,
    IntelligenceSettingsPayload,
    SuggestionRequest,
    UserBehaviorProfileOut,
    IntelligenceAlertOut,
    IntelligenceAlertsSummaryOut,
)
from app.services import db
from app.services.importers import parse_statement_bytes
from app.schemas.models import (
    TransactionCreate, AccountCreate, CreditCardCreate,
    GoalCreate, GoalContributionCreate, RecurringCreate,
    FamilyGroupCreate, FamilyJoin, InvoicePaymentCreate, BoletoSettlementCreate,
)
from app.utils.helpers import (
    calculate_kpis, generate_insights, get_month_range,
)

router = APIRouter(prefix="/api", tags=["api"])


def _parse_optional_date(value: str | None, field_name: str):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} inválida. Use o formato YYYY-MM-DD.",
        ) from exc


def _parse_month(value: str | None) -> date:
    if not value:
        return date.today().replace(day=1)
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="month inválido. Use o formato YYYY-MM.",
        ) from exc


# ---- TRANSACTIONS ------------------------------------------

@router.get("/transactions")
async def api_get_transactions(
    request:  Request,
    user:     dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    p      = request.query_params
    result = db.get_transactions(
        client, user["id"],
        type_          = p.get("type") or None,
        scope          = p.get("scope") or None,
        account_id     = p.get("account_id") or None,
        credit_card_id = p.get("credit_card_id") or None,
        category_id    = p.get("category_id") or None,
        start_date     = _parse_optional_date(p.get("start_date"), "start_date"),
        end_date       = _parse_optional_date(p.get("end_date"), "end_date"),
        search         = p.get("search") or None,
        page           = int(p.get("page", 1)),
        per_page       = int(p.get("per_page", 30)),
    )
    return JSONResponse(result)


@router.post("/transactions", status_code=201)
async def api_create_transaction(
    request: Request,
    payload: TransactionCreate,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    data   = payload.model_dump()
    installment_total = payload.installment_total or payload.total_installments
    try:
        if payload.is_installment and installment_total and installment_total > 1:
            result = db.create_installment_transactions(
                client, user["id"], data, installment_total
            )
        else:
            result = db.create_transaction(client, user["id"], data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(result, status_code=201)


@router.patch("/transactions/{id_}")
async def api_update_transaction(
    id_:     str,
    request: Request,
    payload: dict,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    result = db.update_transaction(client, id_, user["id"], payload)
    return JSONResponse(result)


@router.delete("/transactions/{id_}", status_code=204)
async def api_delete_transaction(
    id_:     str,
    request: Request,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    db.delete_transaction(client, id_, user["id"])
    return JSONResponse(None, status_code=204)


@router.post("/transactions/{id_}/settle-boleto")
async def api_settle_boleto(
    id_: str,
    request: Request,
    payload: BoletoSettlementCreate,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        result = db.settle_boleto(
            client,
            user["id"],
            id_,
            payload.account_id,
            payload.payment_date,
            payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


# ---- ACCOUNTS ----------------------------------------------

@router.get("/accounts")
async def api_get_accounts(request: Request, user: dict = Depends(get_current_user)):
    client   = get_authed_client(request)
    accounts = db.get_accounts(client, user["id"])
    return JSONResponse(accounts)


@router.post("/accounts", status_code=201)
async def api_create_account(
    request: Request,
    payload: AccountCreate,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    result = db.create_account(client, user["id"], payload.model_dump())
    return JSONResponse(result, status_code=201)


# ---- CREDIT CARDS ------------------------------------------

@router.get("/cards")
async def api_get_cards(request: Request, user: dict = Depends(get_current_user)):
    client = get_authed_client(request)
    cards  = db.get_credit_cards(client, user["id"])
    return JSONResponse(cards)


@router.post("/cards", status_code=201)
async def api_create_card(
    request: Request,
    payload: CreditCardCreate,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    result = db.create_credit_card(client, user["id"], payload.model_dump())
    return JSONResponse(result, status_code=201)


@router.post("/invoices/pay")
async def api_pay_invoice(
    request: Request,
    payload: InvoicePaymentCreate,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        result = db.pay_invoice(
            client,
            user["id"],
            payload.invoice_id,
            payload.account_id,
            payload.amount,
            payload.payment_date,
            payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


# ---- CATEGORIES --------------------------------------------

@router.get("/categories")
async def api_get_categories(
    request: Request,
    user:    dict = Depends(get_current_user),
    type:    str  = None,
):
    client     = get_authed_client(request)
    categories = db.get_categories(client, user["id"], type_=type)
    return JSONResponse(categories)


# ---- GOALS -------------------------------------------------

@router.get("/goals")
async def api_get_goals(request: Request, user: dict = Depends(get_current_user)):
    client = get_authed_client(request)
    goals  = db.get_goals(client, user["id"])
    return JSONResponse(goals)


@router.post("/goals", status_code=201)
async def api_create_goal(
    request: Request,
    payload: GoalCreate,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    data   = payload.model_dump()
    result = db.create_goal(client, user["id"], data)
    return JSONResponse(result, status_code=201)


@router.post("/goals/{goal_id}/contribute", status_code=201)
async def api_contribute_goal(
    goal_id: str,
    request: Request,
    payload: GoalContributionCreate,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    db.add_goal_contribution(
        client, user["id"], goal_id,
        payload.amount, payload.notes, payload.date
    )
    return JSONResponse({"success": True}, status_code=201)


# ---- RECURRING ---------------------------------------------

@router.get("/recurring")
async def api_get_recurring(request: Request, user: dict = Depends(get_current_user)):
    client    = get_authed_client(request)
    recurring = db.get_recurring(client, user["id"])
    return JSONResponse(recurring)


@router.post("/recurring", status_code=201)
async def api_create_recurring(
    request: Request,
    payload: RecurringCreate,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    result = db.create_recurring(client, user["id"], payload.model_dump())
    return JSONResponse(result, status_code=201)


@router.patch("/recurring/{id_}")
async def api_pause_recurring(
    id_: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    result = db.pause_recurring(client, id_, user["id"])
    if not result:
        raise HTTPException(status_code=404, detail="Recorrente nao encontrado ou nao foi possivel pausar.")
    return JSONResponse(result)


@router.delete("/recurring/{id_}", status_code=204)
async def api_delete_recurring(
    id_: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    db.delete_recurring(client, id_, user["id"])
    return JSONResponse(None, status_code=204)


# ---- FAMILY ------------------------------------------------

@router.get("/family")
async def api_get_family(request: Request, user: dict = Depends(get_current_user)):
    client = get_authed_client(request)
    group  = db.get_family_group(client, user["id"])
    return JSONResponse(group)


@router.post("/family", status_code=201)
async def api_create_or_join_family(
    request: Request,
    body:    dict,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        if "invite_code" in body:
            result = db.join_family_group(client, user["id"], body["invite_code"])
        else:
            result = db.create_family_group(client, user["id"], body["name"])
        return JSONResponse(result, status_code=201)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- DASHBOARD ---------------------------------------------

@router.get("/dashboard")
async def api_dashboard(
    request: Request,
    user:    dict = Depends(get_current_user),
    month:   str  = None,
):
    client     = get_authed_client(request)
    from dateutil.relativedelta import relativedelta

    ref_date   = _parse_month(month)
    prev_date  = (ref_date - relativedelta(months=1)).replace(day=1)

    current_txs = db.get_month_transactions(client, user["id"], ref_date)
    prev_txs    = db.get_month_transactions(client, user["id"], prev_date)
    accounts    = db.get_accounts(client, user["id"])
    cards       = db.get_credit_cards(client, user["id"])
    goals       = db.get_goals(client, user["id"])
    evolution   = db.get_monthly_evolution(client, user["id"], 6)

    consolidated = sum(float(a["current_balance"]) for a in accounts if a.get("include_in_total", True))
    kpis         = calculate_kpis(current_txs, consolidated, ref_date)
    insights     = generate_insights(current_txs, prev_txs, goals, cards)

    start, end  = get_month_range(ref_date)
    cat_report  = db.get_expenses_by_category(client, user["id"], start, end)

    return JSONResponse({
        "kpis":             kpis,
        "categories":       cat_report,
        "evolution":        evolution,
        "recent_txs":       current_txs[:8],
        "accounts":         accounts,
        "cards":            cards,
        "goals":            goals[:4],
        "insights":         insights,
    })


# ---- NOTIFICATIONS -----------------------------------------

@router.patch("/notifications/{id_}/read", status_code=204)
async def mark_notification_read(
    id_:     str,
    request: Request,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    from datetime import datetime, timezone
    client.table("notifications").update(
        {"is_read": True, "read_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", id_).eq("user_id", user["id"]).execute()
    return JSONResponse(None, status_code=204)


# ---- IMPORTS -----------------------------------------------

@router.post("/imports/preview")
async def api_preview_import(
    request: Request,
    file: UploadFile = File(...),
    bank_hint: str | None = Form(None),
    user: dict = Depends(get_current_user),
):
    _ = get_authed_client(request)
    content = await file.read()
    try:
        result = parse_statement_bytes(file.filename or "arquivo", content, bank_hint=bank_hint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


# ---- INTELLIGENCE ------------------------------------------

@router.get("/intelligence/settings")
async def api_get_intelligence_settings(request: Request, user: dict = Depends(get_current_user)):
    client = get_authed_client(request)
    try:
        data = intelligence_service.get_user_settings(client, user["id"])
    except APIError:
        data = intelligence_service.DEFAULT_SETTINGS.copy()
    return JSONResponse(data)


@router.put("/intelligence/settings")
async def api_save_intelligence_settings(
    request: Request,
    payload: IntelligenceSettingsPayload,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        saved = intelligence_service.save_user_settings(client, user["id"], payload)
    except APIError:
        saved = {**intelligence_service.DEFAULT_SETTINGS, **payload.model_dump()}
    return JSONResponse(saved)


@router.get("/intelligence/rules")
async def api_list_intelligence_rules(request: Request, user: dict = Depends(get_current_user)):
    client = get_authed_client(request)
    try:
        data = intelligence_service.list_rules(client, user["id"])
    except APIError:
        data = []
    return JSONResponse(data)


@router.post("/intelligence/suggestions/transaction")
async def api_transaction_suggestion(
    request: Request,
    payload: SuggestionRequest,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        result = intelligence_service.get_transaction_suggestion(client, user["id"], payload)
    except APIError:
        result = {"found": False, "settings": intelligence_service.DEFAULT_SETTINGS.copy()}
    return JSONResponse(result)


@router.post("/intelligence/feedback")
async def api_transaction_feedback(
    request: Request,
    payload: FeedbackRequest,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        result = intelligence_service.apply_feedback(client, user["id"], payload)
    except APIError:
        result = {"success": False, "rule": None}
    return JSONResponse(result, status_code=201)


@router.put("/intelligence/rules/{rule_id}")
async def api_update_intelligence_rule(
    request: Request,
    rule_id: str,
    payload: dict,  # Define a proper schema later
):
    if not request.session.get("user"):
        return JSONResponse({"detail": "Não autenticado"}, status_code=401)
    user = get_current_user(request)
    client = get_authed_client(request)
    try:
        result = intelligence_service.update_rule(client, user["id"], rule_id, payload)
    except APIError:
        result = {"success": False, "rule": None}
    return JSONResponse(result)


@router.delete("/intelligence/rules/{rule_id}")
async def api_delete_intelligence_rule(
    request: Request,
    rule_id: str,
):
    if not request.session.get("user"):
        return JSONResponse({"detail": "Não autenticado"}, status_code=401)
    user = get_current_user(request)
    client = get_authed_client(request)
    try:
        result = intelligence_service.delete_rule(client, user["id"], rule_id)
    except APIError:
        result = {"success": False}
    return JSONResponse(result)


@router.patch("/intelligence/rules/{rule_id}/toggle")
async def api_toggle_intelligence_rule(
    request: Request,
    rule_id: str,
):
    if not request.session.get("user"):
        return JSONResponse({"detail": "Não autenticado"}, status_code=401)
    user = get_current_user(request)
    client = get_authed_client(request)
    try:
        result = intelligence_service.toggle_rule_active(client, user["id"], rule_id)
    except APIError:
        result = {"success": False, "rule": None}
    return JSONResponse(result)


# ---- USER PROFILE + ALERTS ----------------------------------

@router.get("/intelligence/profile")
async def api_get_user_profile(request: Request, user: dict = Depends(get_current_user)):
    client = get_authed_client(request)
    try:
        profile = intelligence_service.get_user_profile(client, user["id"])
        if profile:
            return JSONResponse(profile)
        else:
            # Try to build profile on demand
            profile = intelligence_service.build_and_store_user_profile(client, user["id"])
            return JSONResponse(profile or {})
    except APIError:
        return JSONResponse({})


@router.post("/intelligence/profile/build")
async def api_build_user_profile(request: Request, user: dict = Depends(get_current_user)):
    client = get_authed_client(request)
    try:
        profile = intelligence_service.build_and_store_user_profile(client, user["id"])
        return JSONResponse({"success": bool(profile), "profile": profile})
    except APIError:
        return JSONResponse({"success": False, "profile": None})


@router.get("/intelligence/alerts")
async def api_list_user_alerts(
    request: Request,
    include_read: bool = True,
    limit: int = 50,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        result = intelligence_service.list_user_alerts(client, user["id"], include_read, limit)
    except APIError:
        result = {"total": 0, "unread": 0, "critical": 0, "items": []}
    return JSONResponse(result)


@router.post("/intelligence/alerts/generate")
async def api_generate_alerts(request: Request, user: dict = Depends(get_current_user)):
    client = get_authed_client(request)
    try:
        alerts = intelligence_service.generate_and_store_alerts(client, user["id"])
        return JSONResponse({"success": True, "generated_count": len(alerts), "alerts": alerts})
    except APIError:
        return JSONResponse({"success": False, "generated_count": 0, "alerts": []})


@router.patch("/intelligence/alerts/{alert_id}/read")
async def api_mark_alert_read(
    request: Request,
    alert_id: str,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        result = intelligence_service.mark_alert_read(client, user["id"], alert_id)
    except APIError:
        result = {"success": False}
    return JSONResponse(result)


@router.patch("/intelligence/alerts/{alert_id}/dismiss")
async def api_dismiss_alert(
    request: Request,
    alert_id: str,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        result = intelligence_service.dismiss_alert(client, user["id"], alert_id)
    except APIError:
        result = {"success": False}
    return JSONResponse(result)


@router.post("/intelligence/alerts/cleanup")
async def api_cleanup_expired_alerts(request: Request, user: dict = Depends(get_current_user)):
    client = get_authed_client(request)
    try:
        result = intelligence_service.cleanup_expired_alerts(client)
    except APIError:
        result = {"success": False, "deleted_count": 0}
    return JSONResponse(result)
