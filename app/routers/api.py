from fastapi import APIRouter, Request, Depends, HTTPException, File, Form, UploadFile
from fastapi.responses import JSONResponse
from datetime import date
import logging
import re
import unicodedata
from postgrest.exceptions import APIError
from app.core.supabase import get_current_user, get_authed_client, get_supabase
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
logger = logging.getLogger(__name__)


def _norm_text(value: str) -> str:
    base = unicodedata.normalize("NFKD", value or "")
    clean = "".join(ch for ch in base if not unicodedata.combining(ch))
    return clean.lower().strip()


def _extract_amount(raw_text: str) -> tuple[float | None, str | None]:
    pattern = re.compile(r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})|\d+(?:[.,]\d{1,2})?)")
    match = pattern.search(raw_text or "")
    if not match:
        return None, None
    token = match.group(1)
    normalized = token.replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        return round(float(normalized), 2), token
    except ValueError:
        return None, None


def _infer_payment_method(raw_text: str) -> str | None:
    text = _norm_text(raw_text)
    mapping = {
        "card": ["credito", "credito", "crédito", "cartao", "cartão", "visa", "master"],
        "pix": ["pix"],
        "boleto": ["boleto"],
        "cash": ["dinheiro", "especie", "espécie", "cash"],
        "account": ["debito", "débito", "conta"],
    }
    for method, tokens in mapping.items():
        if any(token in text for token in tokens):
            return method
    return None


def _infer_transaction_type(raw_text: str) -> str | None:
    text = _norm_text(raw_text)
    income_terms = {"salario", "salário", "pagamento", "bonus", "bônus", "freela", "receita", "reembolso"}
    transfer_terms = {"transferencia", "transferência", "transferir", "ted", "doc"}
    if any(term in text for term in transfer_terms):
        return "transfer"
    if any(term in text for term in income_terms):
        return "income"
    return None


def _find_account_by_text(accounts: list[dict], raw_text: str) -> dict | None:
    text = _norm_text(raw_text)
    for account in accounts:
        name = _norm_text(account.get("name", ""))
        if name and name in text:
            return account
        for chunk in name.split():
            if len(chunk) >= 3 and chunk in text:
                return account
    return None


def _find_category_by_text(categories: list[dict], raw_text: str, tx_type: str | None = None) -> dict | None:
    text = _norm_text(raw_text)
    dictionaries = {
        "alimentacao": ["mercado", "supermercado", "padaria", "ifood", "restaurante", "lanche"],
        "transporte": ["uber", "99", "gasolina", "onibus", "ônibus", "metro", "metrô"],
        "assinaturas": ["netflix", "spotify", "prime", "disney", "assinatura"],
        "moradia": ["aluguel", "condominio", "condomínio", "agua", "água", "luz", "energia", "internet"],
        "receita": ["salario", "salário", "pagamento", "bonus", "bônus", "receita"],
    }
    target_groups = [group for group, tokens in dictionaries.items() if any(token in text for token in tokens)]
    if not target_groups:
        return None

    normalized_categories = []
    for category in categories:
        if tx_type and category.get("type") != tx_type:
            continue
        normalized_categories.append((category, _norm_text(category.get("name", ""))))

    for group in target_groups:
        aliases = {
            "alimentacao": ["alimentacao", "alimentação", "mercado", "supermercado"],
            "transporte": ["transporte", "mobilidade", "combustivel", "combustível"],
            "assinaturas": ["assinaturas", "servicos", "serviços", "streaming"],
            "moradia": ["moradia", "casa", "residencia", "residência", "aluguel", "condominio"],
            "receita": ["salario", "salário", "receita", "renda"],
        }[group]
        for category, norm_name in normalized_categories:
            if any(alias in norm_name for alias in aliases):
                return category

    return None


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


def _attach_family_group_id(client, user_id: str, payload: dict) -> dict:
    scope = payload.get("scope")
    if hasattr(scope, "value"):
        scope = scope.value
    if scope != "shared":
        return payload
    if payload.get("family_group_id"):
        return payload
    group = db.get_family_group(client, user_id)
    if group:
        payload["family_group_id"] = group["id"]
    return payload


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


@router.get("/transactions/recent")
async def api_get_recent_transactions(
    request: Request,
    user: dict = Depends(get_current_user),
    limit: int = 6,
):
    client = get_authed_client(request)
    safe_limit = max(1, min(limit, 12))
    try:
        result = db.get_transactions(
            client,
            user["id"],
            page=1,
            per_page=safe_limit,
        )
    except APIError:
        return JSONResponse([])
    return JSONResponse(result.get("data", []))


@router.get("/transactions/preview")
async def api_preview_transaction_impact(
    request: Request,
    user: dict = Depends(get_current_user),
    account_id: str | None = None,
    amount: float = 0.0,
    type: str = "expense",
):
    client = get_authed_client(request)
    if not account_id:
        return JSONResponse(
            {
                "current_balance": 0.0,
                "projected_balance": 0.0,
                "impact_status": "saudavel",
                "message": "Selecione uma conta para visualizar o impacto.",
            }
        )

    try:
        accounts = db.get_accounts(client, user["id"])
    except APIError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao consultar saldo no Supabase: {exc}",
        ) from exc
    account = next((row for row in accounts if row.get("id") == account_id), None)
    if not account:
        raise HTTPException(status_code=404, detail="Conta nao encontrada.")

    current_balance = round(float(account.get("current_balance") or 0), 2)
    amount = max(float(amount or 0), 0.0)
    tx_type = str(type or "expense")
    if tx_type == "income":
        projected = current_balance + amount
    elif tx_type == "expense":
        projected = current_balance - amount
    else:
        projected = current_balance
    projected = round(projected, 2)

    if projected < 0:
        status = "critico"
        message = "Saldo projetado negativo. Revise antes de salvar."
    elif current_balance > 0 and projected <= current_balance * 0.2:
        status = "atencao"
        message = "Saldo fica apertado apos este lancamento."
    else:
        status = "saudavel"
        message = "Impacto dentro de uma zona confortavel."

    return JSONResponse(
        {
            "current_balance": current_balance,
            "projected_balance": projected,
            "impact_status": status,
            "message": message,
        }
    )


@router.post("/transactions/quick-parse")
async def api_quick_parse_transaction(
    request: Request,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    body = await request.json()
    raw_text = str((body or {}).get("raw_text") or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="raw_text obrigatorio.")

    categories = db.get_categories(client, user["id"])
    accounts = db.get_accounts(client, user["id"])

    amount, amount_token = _extract_amount(raw_text)
    inferred_type = _infer_transaction_type(raw_text)
    payment_method = _infer_payment_method(raw_text)
    account = _find_account_by_text(accounts, raw_text)
    category = _find_category_by_text(categories, raw_text, inferred_type)

    if inferred_type is None and category and category.get("type") in {"income", "expense", "transfer"}:
        inferred_type = category.get("type")
    if inferred_type is None:
        inferred_type = "expense"

    if not category:
        category = _find_category_by_text(categories, raw_text, inferred_type)

    text_for_description = raw_text
    if amount_token:
        text_for_description = text_for_description.replace(amount_token, " ")
    for token in ("crédito", "credito", "débito", "debito", "pix", "boleto", "dinheiro", "conta"):
        text_for_description = re.sub(rf"\b{token}\b", " ", text_for_description, flags=re.I)
    if account and account.get("name"):
        text_for_description = re.sub(re.escape(account["name"]), " ", text_for_description, flags=re.I)
    description = re.sub(r"\s+", " ", text_for_description).strip(" -,.")
    if not description:
        description = raw_text

    flags = []
    if amount is not None:
        flags.append("amount_inferred")
    if account:
        flags.append("account_inferred")
    if payment_method:
        flags.append("payment_method_inferred")
    if category:
        flags.append("category_inferred")
    if inferred_type:
        flags.append("type_inferred")

    return JSONResponse(
        {
            "description": description,
            "amount": amount,
            "account_id": account.get("id") if account else None,
            "account_name": account.get("name") if account else None,
            "payment_method": payment_method or "account",
            "category_id": category.get("id") if category else None,
            "category_name": category.get("name") if category else None,
            "transaction_type": inferred_type,
            "suggestion_flags": flags,
        }
    )


@router.post("/transactions", status_code=201)
async def api_create_transaction(
    request: Request,
    payload: TransactionCreate,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    data   = _attach_family_group_id(client, user["id"], payload.model_dump(mode="json"))
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
    except APIError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Erro Supabase ao salvar transação: {exc}",
        ) from exc
    except Exception as exc:
        logger.exception("Erro inesperado ao salvar transação para user=%s", user.get("id"))
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno ao salvar transação: {exc}",
        ) from exc

    return JSONResponse(result, status_code=201)


@router.patch("/transactions/{id_}")
async def api_update_transaction(
    id_:     str,
    request: Request,
    payload: dict,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    payload = _attach_family_group_id(client, user["id"], payload)
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


@router.patch("/accounts/{id_}")
async def api_update_account(
    id_: str,
    request: Request,
    payload: dict,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        result = db.update_account(client, id_, user["id"], payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except APIError as exc:
        raise HTTPException(status_code=400, detail=f"Erro Supabase ao atualizar conta: {exc}") from exc
    if not result:
        raise HTTPException(status_code=404, detail="Conta nao encontrada.")
    return JSONResponse(result)


@router.delete("/accounts/{id_}", status_code=204)
async def api_delete_account(
    id_: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        removed = db.delete_account(client, id_, user["id"])
    except APIError as exc:
        raise HTTPException(status_code=400, detail=f"Erro Supabase ao excluir conta: {exc}") from exc
    if not removed:
        raise HTTPException(
            status_code=409,
            detail="Nao foi possivel excluir/inativar a conta. Verifique dependencias e permissoes.",
        )
    return JSONResponse(None, status_code=204)


# ---- CREDIT CARDS ------------------------------------------

@router.get("/cards")
async def api_get_cards(request: Request, user: dict = Depends(get_current_user)):
    client = get_authed_client(request)
    cards  = db.get_credit_cards(client, user["id"])
    return JSONResponse(cards)


# ---- PROFILE -----------------------------------------------

@router.get("/profile")
async def api_get_profile(request: Request, user: dict = Depends(get_current_user)):
    client = get_authed_client(request)
    profile = db.get_user_profile(client, user)
    return JSONResponse(profile)


@router.patch("/profile")
async def api_update_profile(
    request: Request,
    payload: dict,
    user: dict = Depends(get_current_user),
):
    full_name = str((payload or {}).get("full_name") or "").strip()
    email = str((payload or {}).get("email") or "").strip()
    if full_name and len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Nome completo deve ter pelo menos 2 caracteres.")
    if email and "@" not in email:
        raise HTTPException(status_code=400, detail="Email invalido.")

    week_start = str((payload or {}).get("week_start") or "monday").lower()
    if week_start not in {"monday", "sunday"}:
        raise HTTPException(status_code=400, detail="Inicio de semana invalido.")

    default_scope = str((payload or {}).get("default_scope") or "personal").lower()
    if default_scope not in {"personal", "shared"}:
        raise HTTPException(status_code=400, detail="Preferencia de ambiente invalida.")

    client = get_authed_client(request)
    try:
        updated = db.update_user_profile(client, user, payload or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Erro ao atualizar perfil: {exc}") from exc

    session_user = dict(request.session.get("user") or {})
    session_user["full_name"] = updated.get("full_name") or session_user.get("full_name")
    session_user["email"] = updated.get("email") or session_user.get("email")
    request.session["user"] = session_user
    return JSONResponse(updated)


@router.post("/profile/password-reset")
async def api_request_password_reset(request: Request, user: dict = Depends(get_current_user)):
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email do usuario nao encontrado.")
    supabase = get_supabase()
    try:
        supabase.auth.reset_password_email(email)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Nao foi possivel iniciar troca de senha: {exc}") from exc
    return JSONResponse({"success": True, "message": "Enviamos um email para redefinicao de senha."})


@router.post("/cards", status_code=201)
async def api_create_card(
    request: Request,
    payload: CreditCardCreate,
    user:    dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    result = db.create_credit_card(client, user["id"], payload.model_dump())
    return JSONResponse(result, status_code=201)


@router.patch("/cards/{id_}")
async def api_update_card(
    id_: str,
    request: Request,
    payload: dict,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        result = db.update_credit_card(client, id_, user["id"], payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except APIError as exc:
        raise HTTPException(status_code=400, detail=f"Erro Supabase ao atualizar cartao: {exc}") from exc
    if not result:
        raise HTTPException(status_code=404, detail="Cartao nao encontrado.")
    return JSONResponse(result)


@router.delete("/cards/{id_}", status_code=204)
async def api_delete_card(
    id_: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    client = get_authed_client(request)
    try:
        removed = db.delete_credit_card(client, id_, user["id"])
    except APIError as exc:
        raise HTTPException(status_code=400, detail=f"Erro Supabase ao excluir cartao: {exc}") from exc
    if not removed:
        raise HTTPException(
            status_code=409,
            detail="Nao foi possivel excluir/inativar o cartao. Verifique dependencias e permissoes.",
        )
    return JSONResponse(None, status_code=204)


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
