from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from postgrest.exceptions import APIError

from app.intelligence import service


class AlertQueryStub:
    def __init__(self, state, table_name):
        self.state = state
        self.table_name = table_name
        self._eq_filters = []
        self._gte_filters = []
        self._lt_filters = []
        self._maybe_single = False
        self._insert_payload = None
        self._update_payload = None
        self._delete_mode = False
        self._order_by = None
        self._desc = False
        self._limit = None

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

    def limit(self, value):
        self._limit = value
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def delete(self):
        self._delete_mode = True
        return self

    def _matches(self, row):
        if not all(row.get(field) == value for field, value in self._eq_filters):
            return False
        if not all(str(row.get(field) or "") >= str(value) for field, value in self._gte_filters):
            return False
        if not all(str(row.get(field) or "") < str(value) for field, value in self._lt_filters):
            return False
        return True

    def execute(self):
        rows = self.state[self.table_name]

        if self._insert_payload is not None:
            payload = deepcopy(self._insert_payload)
            payload.setdefault("id", f"{self.table_name}-{len(rows) + 1}")
            rows.append(payload)
            return SimpleNamespace(data=[deepcopy(payload)], count=1)

        if self._update_payload is not None:
            if "updated_at" in self._update_payload and "updated_at" in self.state.get("missing_alert_columns", set()):
                raise APIError({
                    "code": "PGRST204",
                    "message": "Could not find the 'updated_at' column of 'intelligence_alerts' in the schema cache",
                })

            matched = []
            for row in rows:
                if self._matches(row):
                    row.update(deepcopy(self._update_payload))
                    matched.append(deepcopy(row))
            return SimpleNamespace(data=matched, count=len(matched))

        if self._delete_mode:
            if self._lt_filters and any(field == "expires_at" for field, _value in self._lt_filters):
                if "expires_at" in self.state.get("missing_alert_columns", set()):
                    raise APIError({
                        "code": "PGRST204",
                        "message": "Could not find the 'expires_at' column of 'intelligence_alerts' in the schema cache",
                    })

            kept = []
            deleted = []
            for row in rows:
                if self._matches(row):
                    deleted.append(deepcopy(row))
                else:
                    kept.append(row)
            self.state[self.table_name] = kept
            return SimpleNamespace(data=deleted, count=len(deleted))

        matched = [deepcopy(row) for row in rows if self._matches(row)]
        if self._order_by:
            matched.sort(key=lambda item: item.get(self._order_by), reverse=self._desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        if self._maybe_single:
            return SimpleNamespace(data=matched[0] if matched else None, count=1 if matched else 0)
        return SimpleNamespace(data=matched, count=len(matched))


class AlertClientStub:
    def __init__(self, state):
        self.state = state

    def table(self, name):
        return AlertQueryStub(self.state, name)


def test_generate_and_store_alerts_normalizes_reference_month(monkeypatch):
    state = {
        "transactions": [],
        "user_behavior_profile": [{"user_id": "user-1", "updated_at": "2099-03-01T00:00:00+00:00"}],
        "cards": [],
        "intelligence_alerts": [],
    }
    client = AlertClientStub(state)

    monkeypatch.setattr(
        "app.intelligence.alerts.generate_intelligence_alerts",
        lambda **_kwargs: [
            {
                "alert_type": "low_savings_rate",
                "severity": "warning",
                "title": "Taxa de poupanca baixa",
                "message": "Baixa sobra no mes.",
                "reference_month": "2026-03",
                "amount": 50.0,
                "metadata": {},
            }
        ],
    )

    created = service.generate_and_store_alerts(client, "user-1")

    assert len(created) == 1
    assert created[0]["reference_month"] == "2026-03-01"
    assert state["intelligence_alerts"][0]["reference_month"] == "2026-03-01"


def test_mark_alert_as_read_falls_back_without_updated_at(caplog):
    state = {
        "intelligence_alerts": [{"id": "alert-1", "user_id": "user-1", "is_read": False}],
        "missing_alert_columns": {"updated_at"},
    }
    client = AlertClientStub(state)
    caplog.set_level("WARNING")

    result = service.mark_alert_as_read(client, "user-1", "alert-1")

    assert result == {"success": True}
    assert state["intelligence_alerts"][0]["is_read"] is True
    assert "updated_at column unavailable" in caplog.text


def test_dismiss_alert_updates_timestamp_when_available():
    state = {
        "intelligence_alerts": [{"id": "alert-1", "user_id": "user-1", "is_dismissed": False}],
        "missing_alert_columns": set(),
    }
    client = AlertClientStub(state)

    result = service.dismiss_alert(client, "user-1", "alert-1")

    assert result == {"success": True}
    assert state["intelligence_alerts"][0]["is_dismissed"] is True
    assert "updated_at" in state["intelligence_alerts"][0]


def test_cleanup_expired_alerts_skips_when_expires_at_is_unavailable(caplog):
    state = {
        "intelligence_alerts": [{"id": "alert-1", "user_id": "user-1", "is_dismissed": True}],
        "missing_alert_columns": {"expires_at"},
    }
    client = AlertClientStub(state)
    caplog.set_level("WARNING")

    result = service.cleanup_expired_alerts(client)

    assert result == {"success": False, "deleted_count": 0, "reason": "expires_at_unavailable"}
    assert len(state["intelligence_alerts"]) == 1
    assert "cleanup_expired_alerts skipped" in caplog.text
