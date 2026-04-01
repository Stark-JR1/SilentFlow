"""
Data Access Layer — all Supabase queries go here.
Routers call these functions; they never touch Supabase directly.
"""
from supabase import Client
from datetime import date, datetime
from typing import Optional
from app.core.supabase import get_admin_supabase
from app.utils.helpers import get_month_range, next_recurrence_date
import uuid
from calendar import monthrange


PAYMENT_METHODS = {"account", "pix", "card", "boleto", "cash"}
TRANSACTION_STATUSES = {"paid", "pending", "scheduled", "cancelled"}
INVOICE_STATUSES = {"open", "closed", "partially_paid", "paid", "overdue"}


def _to_iso_date(value):
    return value.isoformat() if isinstance(value, date) else value


def _month_first(year: int, month: int) -> date:
    return date(year, month, 1)


def _safe_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, monthrange(year, month)[1]))


def _shift_month(source: date, months: int) -> date:
    month_index = (source.month - 1) + months
    year = source.year + (month_index // 12)
    month = (month_index % 12) + 1
    return _month_first(year, month)


def _normalize_card_id(payload: dict) -> str | None:
    return payload.get("card_id") or payload.get("credit_card_id")


def _normalize_transaction_payload(payload: dict) -> dict:
    data = dict(payload)
    data["date"] = _to_iso_date(data.get("date"))
    data["due_date"] = _to_iso_date(data.get("due_date"))
    paid_at = data.get("paid_at")
    if isinstance(paid_at, datetime):
        data["paid_at"] = paid_at.isoformat()

    payment_method = str(data.get("payment_method") or "account")
    if payment_method not in PAYMENT_METHODS:
        payment_method = "account"
    data["payment_method"] = payment_method

    card_id = _normalize_card_id(data)
    if card_id:
        data["card_id"] = card_id
        data["credit_card_id"] = card_id
    else:
        data["card_id"] = None
        data["credit_card_id"] = None

    installment_total = data.get("installment_total") or data.get("total_installments")
    if installment_total:
        installment_total = int(installment_total)
    data["installment_total"] = installment_total
    data["total_installments"] = installment_total

    status = data.get("status")
    if hasattr(status, "value"):
        status = status.value
    status = str(status) if status else None
    if status not in TRANSACTION_STATUSES:
        if payment_method == "boleto":
            status = "pending"
        else:
            status = "paid"
    data["status"] = status

    if payment_method in {"account", "pix", "cash"}:
        if not data.get("account_id"):
            raise ValueError("account_id obrigatorio para conta, pix ou dinheiro.")
        data["card_id"] = None
        data["credit_card_id"] = None
        data["invoice_id"] = None
    elif payment_method == "card":
        if not data.get("card_id"):
            raise ValueError("card_id obrigatorio para compras no cartao.")
        data["account_id"] = data.get("account_id") or None
        data["status"] = status if status in {"paid", "scheduled"} else "paid"
    elif payment_method == "boleto":
        if not data.get("due_date"):
            raise ValueError("due_date obrigatorio para boleto.")
        if not data.get("status"):
            data["status"] = "pending"

    if data.get("type") == "income" and payment_method == "card":
        raise ValueError("Receita nao pode usar cartao de credito como forma de recebimento padrao.")

    return data


def _signed_amount(tx_type: str, amount: float) -> float:
    if tx_type == "income":
        return float(amount)
    if tx_type == "expense":
        return -float(amount)
    return 0.0


def _adjust_account_balance(client: Client, account_id: str, delta: float) -> dict | None:
    if not account_id or not delta:
        return None
    current = (
        client.table("accounts")
        .select("id,current_balance")
        .eq("id", account_id)
        .maybe_single()
        .execute()
    )
    row = current.data if current else None
    if not row:
        return None
    new_balance = round(float(row.get("current_balance") or 0) + float(delta), 2)
    resp = (
        client.table("accounts")
        .update({"current_balance": new_balance})
        .eq("id", account_id)
        .select("*")
        .execute()
    )
    return resp.data[0] if resp.data else None


def _find_card(client: Client, user_id: str, card_id: str) -> dict | None:
    for table_name in ("cards", "credit_cards"):
        try:
            resp = (
                client.table(table_name)
                .select("*")
                .eq("id", card_id)
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            if resp and resp.data:
                return resp.data
        except Exception:
            continue
    return None


def _invoice_status(total_amount: float, paid_amount: float, due_date_value: str | date | None) -> str:
    total_amount = round(float(total_amount or 0), 2)
    paid_amount = round(float(paid_amount or 0), 2)
    due_date = date.fromisoformat(due_date_value) if isinstance(due_date_value, str) else due_date_value
    today = date.today()
    if total_amount <= 0:
        return "open"
    if paid_amount >= total_amount:
        return "paid"
    if paid_amount > 0:
        return "partially_paid"
    if due_date and due_date < today:
        return "overdue"
    if due_date and due_date <= today:
        return "closed"
    return "open"


def _ensure_invoice(client: Client, user_id: str, card: dict, tx_date: date) -> dict:
    closing_day = int(card.get("closing_day") or 1)
    due_day = int(card.get("due_day") or closing_day)
    reference_month = _month_first(tx_date.year, tx_date.month)
    if tx_date.day > closing_day:
        reference_month = _shift_month(reference_month, 1)

    reference_iso = reference_month.isoformat()
    existing = (
        client.table("card_invoices")
        .select("*")
        .eq("card_id", card["id"])
        .eq("reference_month", reference_iso)
        .maybe_single()
        .execute()
    )
    if existing and existing.data:
        return existing.data

    closing_date = _safe_day(reference_month.year, reference_month.month, closing_day)
    due_date_value = _safe_day(reference_month.year, reference_month.month, due_day)
    record = {
        "user_id": user_id,
        "card_id": card["id"],
        "reference_month": reference_iso,
        "closing_date": closing_date.isoformat(),
        "due_date": due_date_value.isoformat(),
        "total_amount": 0.0,
        "paid_amount": 0.0,
        "status": "open",
    }
    resp = client.table("card_invoices").insert(record).execute()
    return resp.data[0] if resp.data else record


def _refresh_card_available_limit(client: Client, card: dict, invoice: dict) -> None:
    table_name = "credit_cards" if card.get("credit_limit") is not None else "cards"
    limit_value = float(card.get("limit_amount") or card.get("credit_limit") or 0)
    invoices_resp = (
        client.table("card_invoices")
        .select("total_amount,paid_amount")
        .eq("card_id", card["id"])
        .eq("user_id", card["user_id"])
        .execute()
    )
    outstanding = sum(
        max(float(row.get("total_amount") or 0) - float(row.get("paid_amount") or 0), 0)
        for row in (invoices_resp.data or [])
    )
    available = round(max(limit_value - outstanding, 0), 2)
    payload = {"available_limit": available}
    if table_name == "cards":
        payload["limit_amount"] = limit_value
    client.table(table_name).update(payload).eq("id", card["id"]).execute()


def _add_transaction_to_invoice(client: Client, user_id: str, tx_record: dict) -> dict:
    card = _find_card(client, user_id, tx_record["card_id"])
    if not card:
        raise ValueError("Cartao nao encontrado.")
    tx_date = date.fromisoformat(str(tx_record["date"])[:10])
    invoice = _ensure_invoice(client, user_id, card, tx_date)
    new_total = round(float(invoice.get("total_amount") or 0) + float(tx_record["amount"] or 0), 2)
    new_status = _invoice_status(new_total, invoice.get("paid_amount"), invoice.get("due_date"))
    resp = (
        client.table("card_invoices")
        .update({"total_amount": new_total, "status": new_status})
        .eq("id", invoice["id"])
        .select("*")
        .execute()
    )
    updated_invoice = resp.data[0] if resp.data else {**invoice, "total_amount": new_total, "status": new_status}
    _refresh_card_available_limit(client, card, updated_invoice)
    tx_resp = (
        client.table("transactions")
        .update({"invoice_id": updated_invoice["id"]})
        .eq("id", tx_record["id"])
        .eq("user_id", user_id)
        .select("*")
        .execute()
    )
    return tx_resp.data[0] if tx_resp.data else {**tx_record, "invoice_id": updated_invoice["id"]}


def _apply_transaction_financial_impact(client: Client, user_id: str, tx_record: dict) -> dict:
    payment_method = tx_record.get("payment_method") or "account"
    tx_type = tx_record.get("type")
    amount = float(tx_record.get("amount") or 0)
    status = tx_record.get("status") or "paid"

    if payment_method == "card":
        return _add_transaction_to_invoice(client, user_id, tx_record)

    if payment_method == "boleto":
        return tx_record

    if status != "paid":
        return tx_record

    if tx_type == "transfer" and tx_record.get("account_id") and tx_record.get("to_account_id"):
        _adjust_account_balance(client, tx_record["account_id"], -amount)
        _adjust_account_balance(client, tx_record["to_account_id"], amount)
        return tx_record

    if payment_method in {"account", "pix", "cash"}:
        _adjust_account_balance(client, tx_record.get("account_id"), _signed_amount(tx_type, amount))
    return tx_record


# ---- TRANSACTIONS ------------------------------------------

def get_transactions(
    client: Client,
    user_id: str,
    type_: Optional[str] = None,
    scope: Optional[str] = None,
    account_id: Optional[str] = None,
    credit_card_id: Optional[str] = None,
    category_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 30,
) -> dict:
    query = (
        client.table("transactions")
        .select(
            "*, category:categories(name,icon,color), "
            "account:accounts!transactions_account_id_fkey(name), "
            "card:credit_cards!transactions_credit_card_id_fkey(name)",
            count="exact",
        )
        .is_("deleted_at", "null")
        .eq("user_id", user_id)
    )

    if type_:        query = query.eq("type", type_)
    if scope:        query = query.eq("scope", scope)
    if account_id:   query = query.eq("account_id", account_id)
    if credit_card_id: query = query.eq("credit_card_id", credit_card_id)
    if category_id:  query = query.eq("category_id", category_id)
    if start_date:   query = query.gte("date", start_date.isoformat())
    if end_date:     query = query.lte("date", end_date.isoformat())
    if search:       query = query.ilike("description", f"%{search}%")

    offset = (page - 1) * per_page
    resp = (
        query
        .order("date", desc=True)
        .order("created_at", desc=True)
        .range(offset, offset + per_page - 1)
        .execute()
    )

    count = resp.count or 0
    return {
        "data":        resp.data or [],
        "count":       count,
        "page":        page,
        "per_page":    per_page,
        "total_pages": max(1, -(-count // per_page)),
    }


def get_month_transactions(client: Client, user_id: str, month: date) -> list:
    start, end = get_month_range(month)
    resp = (
        client.table("transactions")
        .select("*, category:categories(name,icon,color)")
        .is_("deleted_at", "null")
        .eq("user_id", user_id)
        .gte("date", start.isoformat())
        .lte("date", end.isoformat())
        .order("date", desc=True)
        .execute()
    )
    return resp.data or []


def create_transaction(client: Client, user_id: str, data: dict) -> dict:
    normalized = _normalize_transaction_payload(data)
    normalized["user_id"] = user_id
    resp = client.table("transactions").insert(normalized).execute()
    record = resp.data[0] if resp.data else {}
    if not record:
        return {}
    return _apply_transaction_financial_impact(client, user_id, record)


def create_installment_transactions(
    client: Client, user_id: str, data: dict, total_installments: int
) -> list:
    group_id   = str(uuid.uuid4())
    normalized = _normalize_transaction_payload(data)
    start_date = normalized["date"] if isinstance(normalized["date"], date) else date.fromisoformat(normalized["date"])
    records    = []

    for i in range(total_installments):
        from dateutil.relativedelta import relativedelta
        d = start_date + relativedelta(months=i)
        record = {
            **normalized,
            "user_id":               user_id,
            "date":                  d.isoformat(),
            "is_installment":        True,
            "installment_number":    i + 1,
            "installment_total":     total_installments,
            "total_installments":    total_installments,
            "installment_group_id":  group_id,
        }
        records.append(record)

    resp = client.table("transactions").insert(records).execute()
    saved = resp.data or []
    return [_apply_transaction_financial_impact(client, user_id, item) for item in saved]


def update_transaction(client: Client, id_: str, user_id: str, data: dict) -> dict:
    if "date" in data and isinstance(data["date"], date):
        data["date"] = data["date"].isoformat()
    resp = (
        client.table("transactions")
        .update(data)
        .eq("id", id_)
        .eq("user_id", user_id)
        .select("*")
        .execute()
    )
    return resp.data[0] if resp.data else {}


def delete_transaction(client: Client, id_: str, user_id: str) -> None:
    client.table("transactions").update(
        {"deleted_at": datetime.utcnow().isoformat()}
    ).eq("id", id_).eq("user_id", user_id).execute()


def pay_invoice(
    client: Client,
    user_id: str,
    invoice_id: str,
    account_id: str,
    amount: float,
    payment_date: date,
    notes: Optional[str] = None,
) -> dict:
    invoice_resp = (
        client.table("card_invoices")
        .select("*")
        .eq("id", invoice_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    invoice = invoice_resp.data if invoice_resp else None
    if not invoice:
        raise ValueError("Fatura nao encontrada.")

    payment_amount = round(float(amount), 2)
    if payment_amount <= 0:
        raise ValueError("Valor do pagamento deve ser positivo.")

    client.table("invoice_payments").insert({
        "user_id": user_id,
        "invoice_id": invoice_id,
        "account_id": account_id,
        "amount": payment_amount,
        "payment_date": payment_date.isoformat() if isinstance(payment_date, date) else payment_date,
        "notes": notes,
        "created_at": datetime.utcnow().isoformat(),
    }).execute()

    _adjust_account_balance(client, account_id, -payment_amount)

    paid_amount = round(float(invoice.get("paid_amount") or 0) + payment_amount, 2)
    total_amount = float(invoice.get("total_amount") or 0)
    status = _invoice_status(total_amount, paid_amount, invoice.get("due_date"))
    resp = (
        client.table("card_invoices")
        .update({"paid_amount": paid_amount, "status": status})
        .eq("id", invoice_id)
        .eq("user_id", user_id)
        .select("*")
        .execute()
    )
    updated = resp.data[0] if resp.data else {**invoice, "paid_amount": paid_amount, "status": status}

    card = _find_card(client, user_id, updated.get("card_id"))
    if card:
        remaining_total = max(round(total_amount - paid_amount, 2), 0)
        merged_invoice = {**updated, "total_amount": remaining_total}
        _refresh_card_available_limit(client, card, merged_invoice)
    return updated


def settle_boleto(
    client: Client,
    user_id: str,
    transaction_id: str,
    account_id: str,
    payment_date: date,
    notes: Optional[str] = None,
) -> dict:
    tx_resp = (
        client.table("transactions")
        .select("*")
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    tx = tx_resp.data if tx_resp else None
    if not tx:
        raise ValueError("Boleto nao encontrado.")
    if (tx.get("payment_method") or "account") != "boleto":
        raise ValueError("A transacao informada nao e um boleto.")
    if tx.get("status") == "paid":
        return tx

    paid_at = datetime.combine(payment_date, datetime.min.time()).isoformat()
    resp = (
        client.table("transactions")
        .update({
            "status": "paid",
            "paid_at": paid_at,
            "account_id": account_id,
            "notes": notes or tx.get("notes"),
        })
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .select("*")
        .execute()
    )
    updated = resp.data[0] if resp.data else {**tx, "status": "paid", "paid_at": paid_at, "account_id": account_id}
    _adjust_account_balance(client, account_id, _signed_amount(updated.get("type"), float(updated.get("amount") or 0)))
    return updated


# ---- ACCOUNTS ----------------------------------------------

def get_accounts(client: Client, user_id: str) -> list:
    resp = (
        client.table("accounts")
        .select("*")
        .is_("deleted_at", "null")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .order("name")
        .execute()
    )
    return resp.data or []


def create_account(client: Client, user_id: str, data: dict) -> dict:
    data["user_id"]         = user_id
    data["current_balance"] = data.get("initial_balance", 0)
    resp = client.table("accounts").insert(data).execute()
    return resp.data[0] if resp.data else {}


def get_consolidated_balance(client: Client, user_id: str) -> float:
    accounts = get_accounts(client, user_id)
    return sum(
        float(a["current_balance"])
        for a in accounts
        if a.get("include_in_total", True)
    )


# ---- CREDIT CARDS ------------------------------------------

def get_credit_cards(client: Client, user_id: str) -> list:
    for table_name in ("credit_cards", "cards"):
        try:
            resp = (
                client.table(table_name)
                .select("*")
                .is_("deleted_at", "null")
                .eq("user_id", user_id)
                .eq("is_active", True)
                .order("name")
                .execute()
            )
            rows = resp.data or []
            if rows:
                normalized = []
                for row in rows:
                    current = dict(row)
                    current.setdefault("brand", current.get("network"))
                    current.setdefault("limit_amount", current.get("credit_limit", 0))
                    current.setdefault("credit_limit", current.get("limit_amount", 0))
                    current.setdefault(
                        "available_limit",
                        round(float(current.get("credit_limit", 0)) - float(current.get("used_amount", 0) or 0), 2),
                    )
                    normalized.append(current)
                return normalized
        except Exception:
            continue
    return []


def create_credit_card(client: Client, user_id: str, data: dict) -> dict:
    limit_amount = data.get("limit_amount", data.get("credit_limit", 0))
    payload = {
        **data,
        "user_id": user_id,
        "brand": data.get("brand") or data.get("network"),
        "bank_name": data.get("bank_name") or data.get("name"),
        "limit_amount": limit_amount,
        "credit_limit": limit_amount,
        "available_limit": limit_amount,
    }
    resp = client.table("credit_cards").insert(payload).execute()
    return resp.data[0] if resp.data else {}


# ---- CATEGORIES --------------------------------------------

def get_categories(client: Client, user_id: str, type_: Optional[str] = None) -> list:
    query = (
        client.table("categories")
        .select("*")
        .or_(f"is_system.eq.true,user_id.eq.{user_id}")
        .order("sort_order")
    )
    if type_:
        query = query.eq("type", type_)
    resp = query.execute()
    return resp.data or []


# ---- GOALS -------------------------------------------------

def get_goals(client: Client, user_id: str, family_group_id: Optional[str] = None) -> list:
    query = (
        client.table("goals")
        .select("*")
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
    )
    if family_group_id:
        query = query.or_(
            f"user_id.eq.{user_id},"
            f"and(scope.eq.shared,family_group_id.eq.{family_group_id})"
        )
    else:
        query = query.eq("user_id", user_id)

    resp = query.execute()
    goals = resp.data or []
    for g in goals:
        target  = float(g.get("target_amount", 1) or 1)
        current = float(g.get("current_amount", 0) or 0)
        g["percentage"] = min(100, round(current / target * 100))
    return goals


def create_goal(client: Client, user_id: str, data: dict) -> dict:
    data["user_id"] = user_id
    if isinstance(data.get("target_date"), date):
        data["target_date"] = data["target_date"].isoformat()
    resp = client.table("goals").insert(data).execute()
    return resp.data[0] if resp.data else {}


def add_goal_contribution(
    client: Client, user_id: str, goal_id: str,
    amount: float, notes: Optional[str], contrib_date: date
) -> None:
    client.table("goal_contributions").insert({
        "goal_id": goal_id,
        "user_id": user_id,
        "amount":  amount,
        "notes":   notes,
        "date":    contrib_date.isoformat(),
    }).execute()


# ---- RECURRING ---------------------------------------------

def get_recurring(client: Client, user_id: str) -> list:
    resp = (
        client.table("recurring_transactions")
        .select("*, category:categories(name,icon,color), account:accounts(name)")
        .eq("user_id", user_id)
        .order("next_date")
        .execute()
    )
    return resp.data or []


def create_recurring(client: Client, user_id: str, data: dict) -> dict:
    data["user_id"]   = user_id
    data["next_date"] = data.get("start_date")
    if isinstance(data.get("start_date"), date):
        data["start_date"] = data["start_date"].isoformat()
    if isinstance(data.get("next_date"), date):
        data["next_date"] = data["next_date"].isoformat()
    if data.get("end_date") and isinstance(data["end_date"], date):
        data["end_date"] = data["end_date"].isoformat()
    resp = client.table("recurring_transactions").insert(data).execute()
    return resp.data[0] if resp.data else {}


def pause_recurring(client: Client, recurring_id: str, user_id: str) -> dict:
    resp = (
        client.table("recurring_transactions")
        .update({"is_active": False})
        .eq("id", recurring_id)
        .eq("user_id", user_id)
        .select("*")
        .execute()
    )
    if resp.data:
        return resp.data[0]

    admin = get_admin_supabase()
    resp = (
        admin.table("recurring_transactions")
        .update({"is_active": False})
        .eq("id", recurring_id)
        .eq("user_id", user_id)
        .select("*")
        .execute()
    )
    return resp.data[0] if resp.data else {}


def delete_recurring(client: Client, recurring_id: str, user_id: str) -> None:
    client.table("recurring_transactions").delete().eq("id", recurring_id).eq(
        "user_id", user_id
    ).execute()


# ---- FAMILY ------------------------------------------------

def get_family_group(client: Client, user_id: str) -> Optional[dict]:
    m = (
        client.table("family_members")
        .select("group_id")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not m or not m.data:
        return None

    group = (
        client.table("family_groups")
        .select("*, members:family_members(*, profile:profiles(full_name,avatar_url))")
        .eq("id", m.data["group_id"])
        .maybe_single()
        .execute()
    )
    return group.data if group else None


def create_family_group(client: Client, user_id: str, name: str) -> dict:
    g = (
        client.table("family_groups")
        .insert({"name": name, "created_by": user_id})
        .execute()
    )
    group = g.data[0]
    client.table("family_members").insert({
        "group_id": group["id"],
        "user_id":  user_id,
        "role":     "owner",
    }).execute()
    return group


def join_family_group(client: Client, user_id: str, invite_code: str) -> dict:
    g = (
        client.table("family_groups")
        .select("*")
        .eq("invite_code", invite_code)
        .maybe_single()
        .execute()
    )
    if not g.data:
        raise ValueError("Código de convite inválido")
    client.table("family_members").insert({
        "group_id": g.data["id"],
        "user_id":  user_id,
        "role":     "member",
    }).execute()
    return g.data


def get_family_summary(client: Client, family_group_id: str) -> dict:
    # Get all members of the family group
    members_resp = client.table("family_members").select("user_id").eq("group_id", family_group_id).execute()
    member_ids = [m["user_id"] for m in members_resp.data or []]
    
    if not member_ids:
        return {
            "total_income": 0,
            "shared_expenses": 0,
            "personal_expenses": {},
            "net_family": 0,
        }
    
    # Get current month transactions for all members
    from datetime import datetime
    now = datetime.now()
    start_of_month = now.replace(day=1).strftime("%Y-%m-%d")
    end_of_month = now.strftime("%Y-%m-%d")
    
    # Total income from all members
    income_resp = client.table("transactions").select("amount").in_("user_id", member_ids).eq("type", "income").gte("date", start_of_month).lte("date", end_of_month).execute()
    total_income = sum(float(t["amount"]) for t in income_resp.data or [])
    
    # Shared expenses
    shared_resp = client.table("transactions").select("amount").in_("user_id", member_ids).eq("type", "expense").eq("scope", "shared").eq("family_group_id", family_group_id).gte("date", start_of_month).lte("date", end_of_month).execute()
    shared_expenses = sum(float(t["amount"]) for t in shared_resp.data or [])
    
    # Personal expenses per member
    personal_expenses = {}
    for user_id in member_ids:
        # Get user profile for name
        profile_resp = client.table("profiles").select("full_name").eq("id", user_id).execute()
        name = (profile_resp.data or [{}])[0].get("full_name", f"Usuário {user_id[:8]}")
        
        # Get personal expenses (not shared)
        personal_resp = client.table("transactions").select("amount").eq("user_id", user_id).eq("type", "expense").neq("scope", "shared").gte("date", start_of_month).lte("date", end_of_month).execute()
        personal_expenses[name] = sum(float(t["amount"]) for t in personal_resp.data or [])
    
    net_family = total_income - shared_expenses
    
    return {
        "total_income": total_income,
        "shared_expenses": shared_expenses,
        "personal_expenses": personal_expenses,
        "net_family": net_family,
    }


# ---- REPORTS -----------------------------------------------

def get_monthly_evolution(client: Client, user_id: str, months: int = 6) -> list:
    from app.utils.helpers import get_last_n_months, format_month_label
    result = []
    for month_start in get_last_n_months(months):
        start, end = get_month_range(month_start)
        resp = (
            client.table("transactions")
            .select("type, amount")
            .is_("deleted_at", "null")
            .eq("user_id", user_id)
            .neq("type", "transfer")
            .gte("date", start.isoformat())
            .lte("date", end.isoformat())
            .execute()
        )
        txs      = resp.data or []
        income   = sum(float(t["amount"]) for t in txs if t["type"] == "income")
        expenses = sum(float(t["amount"]) for t in txs if t["type"] == "expense")
        result.append({
            "month":    format_month_label(month_start),
            "income":   round(income, 2),
            "expenses": round(expenses, 2),
            "net":      round(income - expenses, 2),
        })
    return result


def get_expenses_by_category(
    client: Client, user_id: str, start_date: date, end_date: date
) -> list:
    resp = (
        client.table("transactions")
        .select("amount, category:categories(name,icon,color)")
        .is_("deleted_at", "null")
        .eq("user_id", user_id)
        .eq("type", "expense")
        .gte("date", start_date.isoformat())
        .lte("date", end_date.isoformat())
        .execute()
    )
    txs   = resp.data or []
    total = sum(float(t["amount"]) for t in txs)
    by    = {}
    for tx in txs:
        cat  = tx.get("category") or {}
        name = cat.get("name", "Sem categoria")
        if name not in by:
            by[name] = {"name": name, "icon": cat.get("icon","📦"), "color": cat.get("color","#6c63ff"), "total": 0.0}
        by[name]["total"] += float(tx["amount"])
    return sorted(
        [{"percentage": round(v["total"]/total*100, 1) if total else 0, **v} for v in by.values()],
        key=lambda x: x["total"], reverse=True,
    )
