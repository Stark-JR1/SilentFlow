from datetime import date
from types import SimpleNamespace

from app.schemas.models import PaymentMethod, TransactionScope, TransactionType
from app.services import db
from app.utils.helpers import calculate_kpis


class _FakeTable:
    def __init__(self, state, table_name):
        self.state = state
        self.table_name = table_name
        self._eq = []
        self._insert = None
        self._update = None
        self._maybe_single = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._eq.append((field, value))
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def insert(self, payload):
        self._insert = payload
        return self

    def update(self, payload):
        self._update = payload
        return self

    def execute(self):
        rows = self.state[self.table_name]
        matched = [row for row in rows if all(row.get(k) == v for k, v in self._eq)]

        if self._insert is not None:
            payload = dict(self._insert)
            payload.setdefault("id", f"tx-{len(rows) + 1}")
            rows.append(payload)

            # Simula comportamento externo (trigger) que já abate despesa de conta.
            if (
                payload.get("payment_method") in {"account", "pix", "cash"}
                and payload.get("status") == "paid"
                and payload.get("type") == "expense"
                and payload.get("account_id")
            ):
                acc = next((a for a in self.state["accounts"] if a["id"] == payload["account_id"]), None)
                if acc:
                    acc["current_balance"] = round(float(acc.get("current_balance") or 0) - float(payload["amount"]), 2)

            return SimpleNamespace(data=[payload], count=1)

        if self._update is not None:
            for row in matched:
                row.update(self._update)
            return SimpleNamespace(data=matched, count=len(matched))

        data = matched[0] if (self._maybe_single and matched) else (None if self._maybe_single else matched)
        return SimpleNamespace(data=data, count=(1 if data else 0) if self._maybe_single else len(matched))


class _FakeClient:
    def __init__(self, state):
        self.state = state

    def table(self, name):
        return _FakeTable(self.state, name)


def test_transaction_payload_normalization_handles_enums():
    payload = db._normalize_transaction_payload(
        {
            "type": TransactionType.expense,
            "scope": TransactionScope.shared,
            "payment_method": PaymentMethod.account,
            "status": None,
            "description": "mercado",
            "amount": 80.0,
            "date": date(2026, 4, 4),
            "category_id": "cat-1",
            "account_id": "acc-1",
        }
    )
    assert payload["type"] == "expense"
    assert payload["scope"] == "shared"
    assert payload["payment_method"] == "account"


def test_balance_regression_income_2000_expense_80_results_1920():
    state = {
        "accounts": [
            {"id": "acc-1", "current_balance": 0.0, "user_id": "user-1"},
        ],
        "transactions": [],
    }
    client = _FakeClient(state)

    db.create_transaction(
        client,
        "user-1",
        {
            "type": TransactionType.income,
            "scope": TransactionScope.personal,
            "payment_method": PaymentMethod.account,
            "description": "salario",
            "amount": 2000.0,
            "date": date(2026, 4, 4),
            "category_id": "cat-income",
            "account_id": "acc-1",
        },
    )
    db.create_transaction(
        client,
        "user-1",
        {
            "type": TransactionType.expense,
            "scope": TransactionScope.personal,
            "payment_method": PaymentMethod.account,
            "description": "mercado",
            "amount": 80.0,
            "date": date(2026, 4, 4),
            "category_id": "cat-expense",
            "account_id": "acc-1",
        },
    )

    assert state["accounts"][0]["current_balance"] == 1920.0
    kpis = calculate_kpis(state["transactions"], state["accounts"][0]["current_balance"], date(2026, 4, 1))
    assert kpis["consolidated_balance"] == 1920.0
    assert kpis["total_income"] == 2000.0
    assert kpis["total_expenses"] == 80.0
    assert kpis["net_result"] == 1920.0
