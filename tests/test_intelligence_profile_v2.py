from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from app.intelligence import service


class QueryStub:
    def __init__(self, state, table_name):
        self.state = state
        self.table_name = table_name
        self._eq_filters = []
        self._order_by = None
        self._desc = False
        self._maybe_single = False
        self._upsert_payload = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._eq_filters.append((field, value))
        return self

    def order(self, field, desc=False):
        self._order_by = field
        self._desc = desc
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def limit(self, _value):
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

        matched = [
            deepcopy(row)
            for row in rows
            if all(row.get(field) == value for field, value in self._eq_filters)
        ]
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


def test_get_user_profile_builds_and_persists_when_missing():
    state = {
        "user_behavior_profile": [],
        "categories": [{"id": "cat-salary", "name": "Salario"}],
        "transactions": [
            {
                "user_id": "user-1",
                "date": "2026-01-10",
                "amount": 5000.0,
                "type": "income",
                "category_id": "cat-salary",
                "account_id": "acc-1",
                "card_id": None,
            },
            {
                "user_id": "user-1",
                "date": "2026-01-12",
                "amount": -1000.0,
                "type": "expense",
                "category_id": "cat-home",
                "account_id": "acc-1",
                "card_id": None,
            },
        ],
    }
    client = ClientStub(state)

    profile = service.get_user_profile(client, "user-1")

    assert profile is not None
    assert profile["avg_monthly_income"] == 5000.0
    assert len(state["user_behavior_profile"]) == 1


def test_get_user_profile_reuses_recent_profile(monkeypatch):
    state = {
        "user_behavior_profile": [
            {
                "user_id": "user-1",
                "avg_monthly_income": 1234.0,
                "updated_at": "2099-01-01T00:00:00+00:00",
            }
        ],
        "transactions": [],
    }
    client = ClientStub(state)
    called = {"rebuilt": False}

    def fake_rebuild(_client, _user_id):
        called["rebuilt"] = True
        return {"avg_monthly_income": 9999.0}

    monkeypatch.setattr(service, "build_and_store_user_profile", fake_rebuild)

    profile = service.get_user_profile(client, "user-1")

    assert profile["avg_monthly_income"] == 9999.0
    assert called["rebuilt"] is True


def test_get_user_profile_rebuilds_when_stale(monkeypatch):
    state = {
        "user_behavior_profile": [
            {
                "user_id": "user-1",
                "avg_monthly_income": 1234.0,
                "updated_at": "2020-01-01T00:00:00+00:00",
            }
        ],
        "transactions": [],
    }
    client = ClientStub(state)

    monkeypatch.setattr(
        service,
        "build_and_store_user_profile",
        lambda _client, _user_id: {
            "user_id": "user-1",
            "avg_monthly_income": 4321.0,
            "updated_at": "2099-01-01T00:00:00+00:00",
        },
    )

    profile = service.get_user_profile(client, "user-1")

    assert profile["avg_monthly_income"] == 4321.0


def test_build_and_store_user_profile_ignores_deleted_and_cancelled():
    state = {
        "user_behavior_profile": [],
        "categories": [{"id": "cat-1", "name": "Casa"}],
        "transactions": [
            {
                "user_id": "user-1",
                "date": "2026-04-10",
                "amount": 2000.0,
                "type": "income",
                "category_id": None,
                "account_id": "acc-1",
                "card_id": None,
                "deleted_at": None,
                "status": "paid",
            },
            {
                "user_id": "user-1",
                "date": "2026-04-11",
                "amount": 80.0,
                "type": "expense",
                "category_id": "cat-1",
                "account_id": "acc-1",
                "card_id": None,
                "deleted_at": None,
                "status": "paid",
            },
            {
                "user_id": "user-1",
                "date": "2026-04-12",
                "amount": 9999.0,
                "type": "expense",
                "category_id": "cat-1",
                "account_id": "acc-1",
                "card_id": None,
                "deleted_at": "2026-04-12T10:00:00",
                "status": "paid",
            },
            {
                "user_id": "user-1",
                "date": "2026-04-13",
                "amount": 7777.0,
                "type": "expense",
                "category_id": "cat-1",
                "account_id": "acc-1",
                "card_id": None,
                "deleted_at": None,
                "status": "cancelled",
            },
        ],
    }
    client = ClientStub(state)
    profile = service.build_and_store_user_profile(client, "user-1")

    assert profile["avg_monthly_income"] == 2000.0
    assert profile["avg_monthly_expense"] == 80.0
    assert profile["avg_monthly_savings"] == 1920.0
    assert profile["active_months_count"] == 1
