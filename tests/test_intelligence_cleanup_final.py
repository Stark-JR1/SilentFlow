from __future__ import annotations

import inspect
from types import SimpleNamespace

from app.intelligence import service
from app.intelligence.matcher import token_similarity
from app.intelligence.schemas import IntelligenceSettingsPayload


class AlertQueryStub:
    def __init__(self, state, table_name):
        self.state = state
        self.table_name = table_name
        self._eq_filters = []
        self._lt_filters = []
        self._delete_mode = False

    def delete(self):
        self._delete_mode = True
        return self

    def eq(self, field, value):
        self._eq_filters.append((field, value))
        return self

    def lt(self, field, value):
        self._lt_filters.append((field, value))
        return self

    def execute(self):
        rows = self.state[self.table_name]
        if not self._delete_mode:
            return SimpleNamespace(data=[])

        kept = []
        deleted = []
        for row in rows:
            matches_eq = all(row.get(field) == expected for field, expected in self._eq_filters)
            matches_lt = all(str(row.get(field) or "") < str(expected) for field, expected in self._lt_filters)
            if matches_eq and matches_lt:
                deleted.append(dict(row))
            else:
                kept.append(row)

        self.state[self.table_name] = kept
        return SimpleNamespace(data=deleted)


class AlertClientStub:
    def __init__(self, state):
        self.state = state

    def table(self, name):
        return AlertQueryStub(self.state, name)


def test_token_similarity_preserves_expected_matching_behavior():
    exact = token_similarity("Uber Trip", "Uber Trip")
    partial = token_similarity("Mercado Extra", "Mercado")
    unrelated = token_similarity("Netflix", "Salario")

    assert exact == 1.0
    assert partial > 0
    assert unrelated == 0.0


def test_token_similarity_source_has_no_dead_path():
    source = inspect.getsource(token_similarity)

    assert source.count("return round(jaccard, 3)") == 1
    assert "baseline =" not in source
    assert "intersection = len(tokens_a & tokens_b)" not in source


def test_cleanup_expired_alerts_deletes_only_expired_dismissed_alerts():
    state = {
        "intelligence_alerts": [
            {
                "id": "alert-1",
                "user_id": "user-1",
                "is_dismissed": True,
                "expires_at": "2000-01-01T00:00:00+00:00",
            },
            {
                "id": "alert-2",
                "user_id": "user-1",
                "is_dismissed": False,
                "expires_at": "2000-01-01T00:00:00+00:00",
            },
            {
                "id": "alert-3",
                "user_id": "user-1",
                "is_dismissed": True,
                "expires_at": "2999-01-01T00:00:00+00:00",
            },
        ]
    }
    client = AlertClientStub(state)

    result = service.cleanup_expired_alerts(client)

    assert result == {"success": True, "deleted_count": 1}
    remaining_ids = {row["id"] for row in state["intelligence_alerts"]}
    assert remaining_ids == {"alert-2", "alert-3"}


def test_save_user_settings_warns_planned_import_learning(caplog):
    caplog.set_level("WARNING")

    class ClientStub:
        def table(self, _name):
            class TableStub:
                def upsert(self, payload):
                    self.payload = payload
                    return self

                def execute(self):
                    return SimpleNamespace(data=[self.payload])

            return TableStub()

    payload = IntelligenceSettingsPayload(learn_from_imported_transactions=False)
    result = service.save_user_settings(ClientStub(), "user-1", payload)

    assert result["learn_from_imported_transactions"] is False
    assert "stored for forward compatibility but has no backend effect yet" in caplog.text
