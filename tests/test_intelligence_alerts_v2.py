from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from app.intelligence import service
from app.intelligence.alerts import generate_intelligence_alerts


class QueryStub:
    def __init__(self, state, table_name):
        self.state = state
        self.table_name = table_name
        self._eq_filters = []
        self._gte_filters = []
        self._lt_filters = []
        self._order_by = None
        self._desc = False
        self._maybe_single = False
        self._insert_payload = None
        self._upsert_payload = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._eq_filters.append((field, value))
        return self

    def gte(self, field, value):
        self._gte_filters.append((field, value))
        return self

    def lt(self, field, value):
        self._lt_filters.append((field, value))
        return self

    def order(self, field, desc=False):
        self._order_by = field
        self._desc = desc
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def upsert(self, payload):
        self._upsert_payload = payload
        return self

    def execute(self):
        rows = self.state[self.table_name]

        if self._upsert_payload is not None:
            payload = deepcopy(self._upsert_payload)
            target = next((row for row in rows if row.get("user_id") == payload.get("user_id")), None)
            if target:
                target.update(payload)
                data = [deepcopy(target)]
            else:
                rows.append(payload)
                data = [deepcopy(payload)]
            return SimpleNamespace(data=data, count=len(data))

        if self._insert_payload is not None:
            payload = deepcopy(self._insert_payload)
            payload.setdefault("id", f"{self.table_name}-{len(rows) + 1}")
            rows.append(payload)
            return SimpleNamespace(data=[payload], count=1)

        matched = []
        for row in rows:
            if not all(row.get(field) == value for field, value in self._eq_filters):
                continue
            if not all(str(row.get(field) or "") >= str(value) for field, value in self._gte_filters):
                continue
            if not all(str(row.get(field) or "") < str(value) for field, value in self._lt_filters):
                continue
            matched.append(deepcopy(row))

        if self._order_by:
            matched.sort(key=lambda item: item.get(self._order_by), reverse=self._desc)

        if self._maybe_single:
            return SimpleNamespace(data=matched[0] if matched else None, count=1 if matched else 0)
        return SimpleNamespace(data=matched, count=len(matched))


class ClientStub:
    def __init__(self, state):
        self.state = state

    def table(self, name):
        return QueryStub(self.state, name)


def _flags():
    return SimpleNamespace(intelligence_enabled=True, learning_enabled=True)


def test_generate_intelligence_alerts_covers_all_v2_conditions():
    alerts = generate_intelligence_alerts(
        current_month_transactions=[
            {
                "id": "tx-1",
                "date": "2026-03-10",
                "amount": -500.0,
                "type": "expense",
                "category_id": "cat-food",
                "account_id": "acc-1",
                "card_id": "card-1",
                "description": "Restaurante premium",
            }
        ],
        previous_month_transactions=[
            {
                "id": "tx-prev",
                "date": "2026-02-10",
                "amount": -200.0,
                "type": "expense",
                "category_id": "cat-food",
                "account_id": "acc-1",
                "card_id": "card-1",
                "description": "Restaurante",
            }
        ],
        user_profile={
            "avg_transaction_value": 100.0,
            "avg_monthly_income": 1000.0,
            "avg_monthly_expense": 950.0,
        },
        cards_usage=[
            {"card_id": "card-1", "used": 900.0, "limit": 1000.0, "name": "Cartao Azul"},
        ],
        reference_month="2026-03",
    )

    alert_types = {alert["alert_type"] for alert in alerts}
    assert "category_spike" in alert_types
    assert "unusual_transaction" in alert_types
    assert "low_savings_rate" in alert_types
    assert "high_card_usage" in alert_types
    assert all(alert["reference_month"] == "2026-03-01" for alert in alerts)


def test_generate_and_store_alerts_builds_cards_usage_and_deduplicates(monkeypatch):
    state = {
        "transactions": [
            {
                "id": "tx-1",
                "user_id": "user-1",
                "date": "2026-03-10",
                "amount": -810.0,
                "type": "expense",
                "category_id": "cat-food",
                "account_id": "acc-1",
                "card_id": "card-1",
                "description": "Supermercado",
            },
            {
                "id": "tx-2",
                "user_id": "user-1",
                "date": "2026-02-10",
                "amount": -500.0,
                "type": "expense",
                "category_id": "cat-food",
                "account_id": "acc-1",
                "card_id": "card-1",
                "description": "Supermercado fevereiro",
            },
        ],
        "user_behavior_profile": [
            {
                "user_id": "user-1",
                "avg_transaction_value": 100.0,
                "avg_monthly_income": 2000.0,
                "avg_monthly_expense": 1900.0,
                "updated_at": "2099-03-01T00:00:00+00:00",
            }
        ],
        "cards": [
            {"id": "card-1", "name": "Cartao Azul", "limit_amount": 1000.0, "user_id": "user-1"},
        ],
        "intelligence_alerts": [],
    }
    captured = {}
    client = ClientStub(state)

    monkeypatch.setattr(service, "get_settings", _flags)

    def capture_generate(**kwargs):
        captured.update(kwargs)
        return [
            {
                "alert_type": "high_card_usage",
                "severity": "warning",
                "title": "Uso alto do cartao",
                "message": "Cartao em uso alto.",
                "reference_month": kwargs["reference_month"],
                "card_id": "card-1",
                "amount": 810.0,
                "metadata": {"used": 810.0, "limit": 1000.0},
            }
        ]

    monkeypatch.setattr("app.intelligence.alerts.generate_intelligence_alerts", capture_generate)

    first = service.generate_and_store_alerts(client, "user-1")
    second = service.generate_and_store_alerts(client, "user-1")

    assert first
    assert len(second) == 0
    assert captured["cards_usage"] == [
        {"card_id": "card-1", "used": 810.0, "limit": 1000.0, "name": "Cartao Azul"}
    ]
    assert len(state["intelligence_alerts"]) == 1
    assert state["intelligence_alerts"][0]["reference_month"] == captured["reference_month"]


def test_deduplication_considers_month_and_dimension_keys(monkeypatch):
    state = {
        "transactions": [],
        "user_behavior_profile": [
            {"user_id": "user-1", "updated_at": "2099-03-01T00:00:00+00:00"}
        ],
        "cards": [],
        "intelligence_alerts": [
            {
                "id": "alert-1",
                "user_id": "user-1",
                "alert_type": "category_spike",
                "reference_month": "2026-03-01",
                "category_id": "cat-food",
            }
        ],
    }
    client = ClientStub(state)
    monkeypatch.setattr(service, "get_settings", _flags)
    monkeypatch.setattr(
        "app.intelligence.alerts.generate_intelligence_alerts",
        lambda **_kwargs: [
            {
                "alert_type": "category_spike",
                "severity": "warning",
                "title": "Gasto acima do padrao",
                "message": "Subiu.",
                "reference_month": "2026-03-01",
                "category_id": "cat-food",
                "amount": 500.0,
                "metadata": {},
            },
            {
                "alert_type": "category_spike",
                "severity": "warning",
                "title": "Gasto acima do padrao",
                "message": "Subiu outra categoria.",
                "reference_month": "2026-03-01",
                "category_id": "cat-transport",
                "amount": 400.0,
                "metadata": {},
            },
        ],
    )

    created = service.generate_and_store_alerts(client, "user-1")

    assert len(created) == 1
    assert created[0]["category_id"] == "cat-transport"
