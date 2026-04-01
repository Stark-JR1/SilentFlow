from __future__ import annotations

from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


def _sample_state():
    today = date.today().replace(day=15)
    return {
        "categories": [
            {
                "id": "cat-expense",
                "name": "Mercado",
                "icon": "🛒",
                "color": "#ff6b6b",
                "type": "expense",
                "is_system": True,
            },
            {
                "id": "cat-income",
                "name": "Salario",
                "icon": "💰",
                "color": "#4caf50",
                "type": "income",
                "is_system": True,
            },
        ],
        "accounts": [
            {
                "id": "acc-1",
                "user_id": "user-1",
                "name": "Conta Principal",
                "type": "checking",
                "bank_name": "Banco Teste",
                "icon": "🏦",
                "color": "#123456",
                "initial_balance": 1000.0,
                "current_balance": 800.0,
                "is_active": True,
                "include_in_total": True,
                "deleted_at": None,
            }
        ],
        "transactions": [
            {
                "id": "tx-1",
                "user_id": "user-1",
                "category_id": "cat-income",
                "category": {"name": "Salario", "icon": "💰", "color": "#4caf50"},
                "account_id": "acc-1",
                "payment_method": "account",
                "status": "paid",
                "type": "income",
                "scope": "personal",
                "description": "Salario",
                "amount": 3000.0,
                "date": today.isoformat(),
                "notes": None,
                "deleted_at": None,
                "created_at": f"{today.isoformat()}T10:00:00",
            },
            {
                "id": "tx-2",
                "user_id": "user-1",
                "category_id": "cat-expense",
                "category": {"name": "Mercado", "icon": "🛒", "color": "#ff6b6b"},
                "account_id": "acc-1",
                "payment_method": "account",
                "status": "paid",
                "type": "expense",
                "scope": "personal",
                "description": "Compras do mes",
                "amount": 450.0,
                "date": today.isoformat(),
                "notes": None,
                "deleted_at": None,
                "created_at": f"{today.isoformat()}T12:00:00",
            },
        ],
        "cards": [
            {
                "id": "card-1",
                "user_id": "user-1",
                "name": "Cartao Azul",
                "bank_name": "Banco Teste",
                "brand": "visa",
                "limit_amount": 2000.0,
                "credit_limit": 2000.0,
                "available_limit": 900.0,
                "closing_day": 10,
                "due_day": 20,
                "account_id": "acc-1",
                "is_active": True,
                "deleted_at": None,
            }
        ],
        "card_invoices": [],
        "invoice_payments": [],
        "goals": [
            {
                "id": "goal-1",
                "user_id": "user-1",
                "name": "Reserva",
                "target_amount": 5000.0,
                "current_amount": 4100.0,
                "is_completed": False,
                "scope": "personal",
                "deleted_at": None,
            }
        ],
        "recurring": [
            {
                "id": "rec-1",
                "user_id": "user-1",
                "category_id": "cat-expense",
                "type": "expense",
                "scope": "personal",
                "description": "Internet",
                "amount": 120.0,
                "frequency": "monthly",
                "start_date": today.replace(day=5).isoformat(),
                "next_date": today.replace(day=5).isoformat(),
                "is_active": True,
            }
        ],
        "family_group": None,
        "notifications": [
            {
                "id": "note-1",
                "user_id": "user-1",
                "title": "Lembrete",
                "is_read": False,
                "created_at": f"{today.isoformat()}T08:00:00",
            }
        ],
        "intelligence_settings": [],
        "learning_rules": [],
        "learning_feedback": [],
        "recurrence_patterns": [],
    }


class FakeQuery:
    def __init__(self, state, table_name):
        self.state = state
        self.table_name = table_name
        self._eq_filters = []
        self._limit = None
        self._update_data = None
        self._delete_mode = False
        self._insert_data = None
        self._upsert_data = None
        self._order_by = None
        self._desc = False
        self._maybe_single = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._eq_filters.append((field, value))
        return self

    def order(self, field, desc=False):
        self._order_by = field
        self._desc = desc
        return self

    def limit(self, value):
        self._limit = value
        return self

    def update(self, payload):
        self._update_data = payload
        return self

    def insert(self, payload):
        self._insert_data = payload
        return self

    def upsert(self, payload):
        self._upsert_data = payload
        return self

    def delete(self):
        self._delete_mode = True
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def execute(self):
        rows = self.state[self.table_name]
        matched = [row for row in rows if all(row.get(k) == v for k, v in self._eq_filters)]

        if self._upsert_data is not None:
            payload = deepcopy(self._upsert_data)
            key_fields = ["id"] if payload.get("id") else ["user_id"]
            target = next(
                (
                    row for row in rows
                    if all(row.get(field) == payload.get(field) for field in key_fields)
                ),
                None,
            )
            if target:
                target.update(payload)
                data = deepcopy([target])
            else:
                rows.append(payload)
                data = deepcopy([payload])
            return SimpleNamespace(data=data, count=len(data))

        if self._insert_data is not None:
            payload = self._insert_data
            records = payload if isinstance(payload, list) else [payload]
            inserted = []
            for item in records:
                record = deepcopy(item)
                record.setdefault("id", f"{self.table_name}-{len(rows) + 1}")
                rows.append(record)
                inserted.append(record)
            return SimpleNamespace(data=deepcopy(inserted), count=len(inserted))

        if self._delete_mode:
            self.state[self.table_name] = [
                row for row in rows if not all(row.get(k) == v for k, v in self._eq_filters)
            ]
            return SimpleNamespace(data=deepcopy(matched), count=len(matched))

        if self._update_data is not None:
            for row in matched:
                row.update(self._update_data)
            return SimpleNamespace(data=deepcopy(matched), count=len(matched))

        data = deepcopy(matched)
        if self._order_by:
            data.sort(key=lambda item: item.get(self._order_by), reverse=self._desc)
        if self._limit is not None:
            data = data[: self._limit]
        if self._maybe_single:
            return SimpleNamespace(data=data[0] if data else None, count=1 if data else 0)
        return SimpleNamespace(data=data, count=len(data))


class FakeAuthedClient:
    def __init__(self, state):
        self.state = state

    def table(self, name):
        table_map = {
            "notifications": "notifications",
            "recurring_transactions": "recurring",
            "intelligence_settings": "intelligence_settings",
            "transaction_learning_rules": "learning_rules",
            "transaction_learning_feedback": "learning_feedback",
            "transaction_recurrence_patterns": "recurrence_patterns",
        }
        return FakeQuery(self.state, table_map[name])


class FakeSupabaseAuth:
    def __init__(self, users):
        self.users = users
        self.last_reset_email = None
        self.last_reset_options = None
        self.current_access_token = None
        self.current_refresh_token = None
        self.updated_password = None

    def sign_in_with_password(self, payload):
        email = payload.get("email", "")
        password = payload.get("password", "")
        user = self.users.get(email)
        if not user or user["password"] != password:
            raise Exception("Invalid login credentials")
        return SimpleNamespace(
            user=SimpleNamespace(
                id=user["id"],
                email=email,
                user_metadata={"full_name": user["full_name"]},
            ),
            session=SimpleNamespace(access_token=f"token-{user['id']}"),
        )

    def sign_up(self, payload):
        email = payload["email"]
        if email in self.users:
            raise Exception("User already registered")
        user = {
            "id": f"user-{len(self.users) + 1}",
            "full_name": payload.get("options", {}).get("data", {}).get("full_name", ""),
            "password": payload["password"],
        }
        self.users[email] = user
        return SimpleNamespace(
            user=SimpleNamespace(
                id=user["id"],
                email=email,
                user_metadata={"full_name": user["full_name"]},
            )
        )

    def reset_password_email(self, email, options=None):
        if "@" not in email:
            raise Exception("Invalid email")
        self.last_reset_email = email
        self.last_reset_options = options or {}
        return True

    def set_session(self, access_token, refresh_token):
        self.current_access_token = access_token
        self.current_refresh_token = refresh_token
        return SimpleNamespace(
            user=SimpleNamespace(id="user-1", email="user@example.com", user_metadata={"full_name": "Usuario Teste"}),
            session=SimpleNamespace(access_token=access_token, refresh_token=refresh_token),
        )

    def set_auth(self, access_token):
        self.current_access_token = access_token
        return True

    def update_user(self, payload):
        password = payload.get("password") if isinstance(payload, dict) else None
        if not self.current_access_token:
            raise Exception("Missing access token")
        if not password:
            raise Exception("Password required")
        self.updated_password = password
        return SimpleNamespace(user=SimpleNamespace(id="user-1", email="user@example.com"))

    def sign_out(self):
        return True


class FakeSupabase:
    def __init__(self, users):
        self.auth = FakeSupabaseAuth(users)


@pytest.fixture
def app_client(monkeypatch):
    import main
    from app.routers import api as api_router
    from app.routers import auth as auth_router
    from app.routers import pages as pages_router
    from app.services import db

    state = _sample_state()
    users = {
        "user@example.com": {
            "id": "user-1",
            "full_name": "Usuario Teste",
            "password": "senha123",
        }
    }

    def active_accounts(user_id):
        return [
            acc
            for acc in state["accounts"]
            if acc["user_id"] == user_id and not acc.get("deleted_at") and acc.get("is_active", True)
        ]

    def active_cards(user_id):
        return [
            card
            for card in state["cards"]
            if card["user_id"] == user_id and not card.get("deleted_at") and card.get("is_active", True)
        ]

    def active_goals(user_id):
        goals = [
            goal
            for goal in state["goals"]
            if goal["user_id"] == user_id and not goal.get("deleted_at")
        ]
        for goal in goals:
            target = float(goal.get("target_amount", 1) or 1)
            current = float(goal.get("current_amount", 0) or 0)
            goal["percentage"] = min(100, round(current / target * 100))
        return goals

    def active_transactions(user_id):
        return [
            tx
            for tx in state["transactions"]
            if tx["user_id"] == user_id and not tx.get("deleted_at")
        ]

    def shift_month(source, months):
        month_index = (source.month - 1) + months
        year = source.year + (month_index // 12)
        month = (month_index % 12) + 1
        return date(year, month, 1)

    def safe_day(year, month, day):
        from calendar import monthrange
        return date(year, month, min(day, monthrange(year, month)[1]))

    def signed_amount(tx_type, amount):
        if tx_type == "income":
            return float(amount)
        if tx_type == "expense":
            return -float(amount)
        return 0.0

    def get_account_ref(account_id):
        return next((acc for acc in state["accounts"] if acc["id"] == account_id), None)

    def get_card_ref(card_id):
        return next((card for card in state["cards"] if card["id"] == card_id), None)

    def adjust_account_balance(account_id, delta):
        account = get_account_ref(account_id)
        if account and delta:
            account["current_balance"] = round(float(account.get("current_balance", 0)) + float(delta), 2)
        return account

    def invoice_status(total_amount, paid_amount, due_date_value):
        total_amount = round(float(total_amount or 0), 2)
        paid_amount = round(float(paid_amount or 0), 2)
        due_date = date.fromisoformat(due_date_value) if isinstance(due_date_value, str) else due_date_value
        if total_amount <= 0:
            return "open"
        if paid_amount >= total_amount:
            return "paid"
        if paid_amount > 0:
            return "partially_paid"
        if due_date and due_date < date.today():
            return "overdue"
        return "open"

    def ensure_invoice(user_id, card_id, tx_date):
        card = get_card_ref(card_id)
        closing_day = int(card.get("closing_day") or 1)
        due_day = int(card.get("due_day") or closing_day)
        reference_month = date(tx_date.year, tx_date.month, 1)
        if tx_date.day > closing_day:
            reference_month = shift_month(reference_month, 1)
        reference_iso = reference_month.isoformat()
        existing = next(
            (
                inv for inv in state["card_invoices"]
                if inv["user_id"] == user_id and inv["card_id"] == card_id and inv["reference_month"] == reference_iso
            ),
            None,
        )
        if existing:
            return existing
        invoice = {
            "id": f"inv-{len(state['card_invoices']) + 1}",
            "user_id": user_id,
            "card_id": card_id,
            "reference_month": reference_iso,
            "closing_date": safe_day(reference_month.year, reference_month.month, closing_day).isoformat(),
            "due_date": safe_day(reference_month.year, reference_month.month, due_day).isoformat(),
            "total_amount": 0.0,
            "paid_amount": 0.0,
            "status": "open",
        }
        state["card_invoices"].append(invoice)
        return invoice

    def update_card_available_limit(card_id):
        card = get_card_ref(card_id)
        if not card:
            return None
        outstanding = sum(
            max(float(inv.get("total_amount", 0)) - float(inv.get("paid_amount", 0)), 0)
            for inv in state["card_invoices"]
            if inv["card_id"] == card_id and inv["user_id"] == card["user_id"]
        )
        limit_amount = float(card.get("limit_amount", card.get("credit_limit", 0)) or 0)
        card["credit_limit"] = limit_amount
        card["limit_amount"] = limit_amount
        card["available_limit"] = round(max(limit_amount - outstanding, 0), 2)
        return card

    def normalize_tx_payload(payload):
        data = deepcopy(payload)
        payment_method = data.get("payment_method") or "account"
        data["payment_method"] = payment_method
        data["status"] = data.get("status") or ("pending" if payment_method == "boleto" else "paid")
        card_id = data.get("card_id") or data.get("credit_card_id")
        data["card_id"] = card_id
        data["credit_card_id"] = card_id
        installment_total = data.get("installment_total") or data.get("total_installments")
        data["installment_total"] = installment_total
        data["total_installments"] = installment_total
        if hasattr(data.get("date"), "isoformat"):
            data["date"] = data["date"].isoformat()
        if hasattr(data.get("due_date"), "isoformat"):
            data["due_date"] = data["due_date"].isoformat()
        return data

    def apply_financial_impact(record):
        payment_method = record.get("payment_method") or "account"
        if payment_method == "card":
            tx_date = date.fromisoformat(record["date"])
            invoice = ensure_invoice(record["user_id"], record["card_id"], tx_date)
            invoice["total_amount"] = round(float(invoice.get("total_amount", 0)) + float(record["amount"]), 2)
            invoice["status"] = invoice_status(invoice["total_amount"], invoice["paid_amount"], invoice["due_date"])
            record["invoice_id"] = invoice["id"]
            update_card_available_limit(record["card_id"])
            return record
        if payment_method == "boleto":
            return record
        if record.get("status") == "paid" and payment_method in {"account", "pix", "cash"}:
            adjust_account_balance(record.get("account_id"), signed_amount(record.get("type"), record.get("amount", 0)))
        return record

    def get_authed_client(request):
        user = request.session.get("user")
        if not user or not user.get("access_token"):
            raise HTTPException(status_code=401, detail="Nao autenticado")
        return FakeAuthedClient(state)

    def get_accounts(_client, user_id):
        return deepcopy(active_accounts(user_id))

    def create_account(_client, user_id, payload):
        record = {
            "id": f"acc-{len(state['accounts']) + 1}",
            "user_id": user_id,
            "current_balance": payload.get("initial_balance", 0.0),
            "include_in_total": True,
            "is_active": True,
            "deleted_at": None,
            **payload,
        }
        state["accounts"].append(record)
        return deepcopy(record)

    def get_transactions(
        _client,
        user_id,
        type_=None,
        scope=None,
        account_id=None,
        credit_card_id=None,
        category_id=None,
        start_date=None,
        end_date=None,
        search=None,
        page=1,
        per_page=30,
    ):
        rows = active_transactions(user_id)
        if type_:
            rows = [tx for tx in rows if tx["type"] == type_]
        if scope:
            rows = [tx for tx in rows if tx["scope"] == scope]
        if account_id:
            rows = [tx for tx in rows if tx.get("account_id") == account_id]
        if credit_card_id:
            rows = [tx for tx in rows if tx.get("credit_card_id") == credit_card_id]
        if category_id:
            rows = [tx for tx in rows if tx.get("category_id") == category_id]
        if start_date:
            rows = [tx for tx in rows if tx["date"] >= start_date.isoformat()]
        if end_date:
            rows = [tx for tx in rows if tx["date"] <= end_date.isoformat()]
        if search:
            rows = [tx for tx in rows if search.lower() in tx["description"].lower()]
        offset = (page - 1) * per_page
        sliced = rows[offset : offset + per_page]
        return {
            "data": deepcopy(sliced),
            "count": len(rows),
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, -(-len(rows) // per_page)),
        }

    def get_month_transactions(_client, user_id, month):
        return [
            deepcopy(tx)
            for tx in active_transactions(user_id)
            if tx["date"].startswith(f"{month.year:04d}-{month.month:02d}")
        ]

    def create_transaction(_client, user_id, payload):
        payload = normalize_tx_payload(payload)
        if payload["payment_method"] in {"account", "pix", "cash"} and not payload.get("account_id"):
            raise ValueError("account_id obrigatorio")
        if payload["payment_method"] == "card" and not payload.get("card_id"):
            raise ValueError("card_id obrigatorio")
        if payload["payment_method"] == "boleto" and not payload.get("due_date"):
            raise ValueError("due_date obrigatorio")
        category = next(cat for cat in state["categories"] if cat["id"] == payload["category_id"])
        record = {
            "id": f"tx-{len(state['transactions']) + 1}",
            "user_id": user_id,
            "category": {
                "name": category["name"],
                "icon": category["icon"],
                "color": category["color"],
            },
            "deleted_at": None,
            "created_at": f"{payload['date']}T09:00:00",
            **payload,
        }
        state["transactions"].append(record)
        return deepcopy(apply_financial_impact(record))

    def update_transaction(_client, tx_id, user_id, payload):
        for tx in state["transactions"]:
            if tx["id"] == tx_id and tx["user_id"] == user_id and not tx.get("deleted_at"):
                for key, value in payload.items():
                    tx[key] = value.isoformat() if hasattr(value, "isoformat") else value
                return deepcopy(tx)
        return {}

    def delete_transaction(_client, tx_id, user_id):
        for tx in state["transactions"]:
            if tx["id"] == tx_id and tx["user_id"] == user_id and not tx.get("deleted_at"):
                tx["deleted_at"] = "deleted"
                return None
        return None

    def get_credit_cards(_client, user_id):
        return deepcopy(active_cards(user_id))

    def create_credit_card(_client, user_id, payload):
        limit_amount = payload.get("limit_amount", payload.get("credit_limit", 0))
        record = {
            "id": f"card-{len(state['cards']) + 1}",
            "user_id": user_id,
            "credit_limit": limit_amount,
            "limit_amount": limit_amount,
            "available_limit": limit_amount,
            "is_active": True,
            "deleted_at": None,
            **payload,
        }
        state["cards"].append(record)
        return deepcopy(record)

    def create_installment_transactions(_client, user_id, payload, total_installments):
        payload = normalize_tx_payload(payload)
        from dateutil.relativedelta import relativedelta
        start_date = date.fromisoformat(payload["date"])
        group_id = str(uuid4())
        created = []
        for idx in range(total_installments):
            current_date = start_date + relativedelta(months=idx)
            item = {
                **payload,
                "date": current_date.isoformat(),
                "is_installment": True,
                "installment_number": idx + 1,
                "installment_total": total_installments,
                "total_installments": total_installments,
                "installment_group_id": group_id,
            }
            created.append(create_transaction(_client, user_id, item))
        return created

    def pay_invoice(_client, user_id, invoice_id, account_id, amount, payment_date, notes=None):
        invoice = next((inv for inv in state["card_invoices"] if inv["id"] == invoice_id and inv["user_id"] == user_id), None)
        if not invoice:
            raise ValueError("Fatura nao encontrada.")
        payment = {
            "id": f"pay-{len(state['invoice_payments']) + 1}",
            "user_id": user_id,
            "invoice_id": invoice_id,
            "account_id": account_id,
            "amount": float(amount),
            "payment_date": payment_date.isoformat() if hasattr(payment_date, "isoformat") else payment_date,
            "notes": notes,
            "created_at": date.today().isoformat(),
        }
        state["invoice_payments"].append(payment)
        adjust_account_balance(account_id, -float(amount))
        invoice["paid_amount"] = round(float(invoice.get("paid_amount", 0)) + float(amount), 2)
        invoice["status"] = invoice_status(invoice["total_amount"], invoice["paid_amount"], invoice["due_date"])
        update_card_available_limit(invoice["card_id"])
        return deepcopy(invoice)

    def settle_boleto(_client, user_id, transaction_id, account_id, payment_date, notes=None):
        tx = next((row for row in state["transactions"] if row["id"] == transaction_id and row["user_id"] == user_id), None)
        if not tx:
            raise ValueError("Boleto nao encontrado.")
        tx["status"] = "paid"
        tx["paid_at"] = payment_date.isoformat() if hasattr(payment_date, "isoformat") else payment_date
        tx["account_id"] = account_id
        if notes:
            tx["notes"] = notes
        adjust_account_balance(account_id, signed_amount(tx["type"], tx["amount"]))
        return deepcopy(tx)

    def get_categories(_client, _user_id, type_=None):
        rows = state["categories"]
        if type_:
            rows = [cat for cat in rows if cat["type"] == type_]
        return deepcopy(rows)

    def get_goals(_client, user_id, family_group_id=None):
        return deepcopy(active_goals(user_id))

    def create_goal(_client, user_id, payload):
        record = {
            "id": f"goal-{len(state['goals']) + 1}",
            "user_id": user_id,
            "current_amount": 0.0,
            "is_completed": False,
            "deleted_at": None,
            **payload,
        }
        if hasattr(record.get("target_date"), "isoformat"):
            record["target_date"] = record["target_date"].isoformat()
        state["goals"].append(record)
        return deepcopy(record)

    def add_goal_contribution(_client, user_id, goal_id, amount, notes, contrib_date):
        for goal in state["goals"]:
            if goal["id"] == goal_id and goal["user_id"] == user_id:
                goal["current_amount"] = float(goal.get("current_amount", 0)) + float(amount)
                return None
        return None

    def get_recurring(_client, user_id):
        return deepcopy([row for row in state["recurring"] if row["user_id"] == user_id])

    def create_recurring(_client, user_id, payload):
        record = {
            "id": f"rec-{len(state['recurring']) + 1}",
            "user_id": user_id,
            "next_date": payload["start_date"].isoformat(),
            **payload,
        }
        if hasattr(record.get("start_date"), "isoformat"):
            record["start_date"] = record["start_date"].isoformat()
        if hasattr(record.get("end_date"), "isoformat"):
            record["end_date"] = record["end_date"].isoformat()
        state["recurring"].append(record)
        return deepcopy(record)

    def pause_recurring(_client, recurring_id, user_id):
        for row in state["recurring"]:
            if row["id"] == recurring_id and row["user_id"] == user_id:
                row["is_active"] = False
                return deepcopy(row)
        return {}

    def delete_recurring(_client, recurring_id, user_id):
        state["recurring"] = [
            row
            for row in state["recurring"]
            if not (row["id"] == recurring_id and row["user_id"] == user_id)
        ]
        return None

    def get_family_group(_client, user_id):
        group = state["family_group"]
        if not group:
            return None
        members = [member for member in group["members"] if member["user_id"] == user_id]
        return deepcopy(group if members else None)

    def create_family_group(_client, user_id, name):
        state["family_group"] = {
            "id": "family-1",
            "name": name,
            "invite_code": "JOIN123",
            "members": [
                {
                    "user_id": user_id,
                    "role": "owner",
                    "profile": {"full_name": "Usuario Teste", "avatar_url": None},
                }
            ],
        }
        return deepcopy(state["family_group"])

    def join_family_group(_client, user_id, invite_code):
        if not state["family_group"] or invite_code != state["family_group"]["invite_code"]:
            raise ValueError("Código de convite inválido")
        state["family_group"]["members"].append(
            {
                "user_id": user_id,
                "role": "member",
                "profile": {"full_name": "Convidado", "avatar_url": None},
            }
        )
        return deepcopy(state["family_group"])

    def get_monthly_evolution(_client, user_id, months=6):
        txs = active_transactions(user_id)
        income = sum(tx["amount"] for tx in txs if tx["type"] == "income")
        expenses = sum(tx["amount"] for tx in txs if tx["type"] == "expense")
        return [
            {"month": "Jan/26", "income": income, "expenses": expenses, "net": income - expenses}
            for _ in range(months)
        ]

    def get_expenses_by_category(_client, user_id, start_date, end_date):
        rows = [
            tx
            for tx in active_transactions(user_id)
            if tx["type"] == "expense" and start_date.isoformat() <= tx["date"] <= end_date.isoformat()
        ]
        total = sum(tx["amount"] for tx in rows) or 1
        return [
            {
                "name": tx["category"]["name"],
                "icon": tx["category"]["icon"],
                "color": tx["category"]["color"],
                "total": tx["amount"],
                "percentage": round(tx["amount"] / total * 100, 1),
            }
            for tx in rows
        ]

    fake_supabase = FakeSupabase(users)
    monkeypatch.setattr(auth_router, "get_supabase", lambda: fake_supabase)
    monkeypatch.setattr(api_router, "get_authed_client", get_authed_client)
    monkeypatch.setattr(pages_router, "get_authed_client", get_authed_client)

    monkeypatch.setattr(db, "get_accounts", get_accounts)
    monkeypatch.setattr(db, "create_account", create_account)
    monkeypatch.setattr(db, "get_transactions", get_transactions)
    monkeypatch.setattr(db, "get_month_transactions", get_month_transactions)
    monkeypatch.setattr(db, "create_transaction", create_transaction)
    monkeypatch.setattr(db, "create_installment_transactions", create_installment_transactions)
    monkeypatch.setattr(db, "update_transaction", update_transaction)
    monkeypatch.setattr(db, "delete_transaction", delete_transaction)
    monkeypatch.setattr(db, "get_credit_cards", get_credit_cards)
    monkeypatch.setattr(db, "create_credit_card", create_credit_card)
    monkeypatch.setattr(db, "pay_invoice", pay_invoice)
    monkeypatch.setattr(db, "settle_boleto", settle_boleto)
    monkeypatch.setattr(db, "get_categories", get_categories)
    monkeypatch.setattr(db, "get_goals", get_goals)
    monkeypatch.setattr(db, "create_goal", create_goal)
    monkeypatch.setattr(db, "add_goal_contribution", add_goal_contribution)
    monkeypatch.setattr(db, "get_recurring", get_recurring)
    monkeypatch.setattr(db, "create_recurring", create_recurring)
    monkeypatch.setattr(db, "get_family_group", get_family_group)
    monkeypatch.setattr(db, "create_family_group", create_family_group)
    monkeypatch.setattr(db, "join_family_group", join_family_group)
    monkeypatch.setattr(db, "get_monthly_evolution", get_monthly_evolution)
    monkeypatch.setattr(db, "get_expenses_by_category", get_expenses_by_category)

    client = TestClient(main.app)

    def login(email="user@example.com", password="senha123"):
        return client.post(
            "/auth/login",
            data={"email": email, "password": password},
            follow_redirects=False,
        )

    return SimpleNamespace(client=client, state=state, users=users, login=login, supabase=fake_supabase)


@pytest.fixture
def logged_client(app_client):
    response = app_client.login()
    assert response.status_code == 302
    return app_client




